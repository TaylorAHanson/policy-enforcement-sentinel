"""What the policies in ``policies/`` actually say, as structured data.

The UI needs to render a policy's owner, category, severity, and requested
action next to its source; the agent needs the same information to answer
questions about coverage; the safety suite needs it to assert that nothing
ships above Tier 1. Parsing Rego with regular expressions to get it would be a
slow-motion disaster, so this module asks OPA instead:

* ``opa inspect -a`` returns the ``# METADATA`` annotation blocks, which is
  where package-level facts (title, owner, domain) live.
* ``opa eval`` returns each package's ``rule_metadata`` value, which is where
  per-rule facts live. Evaluating it means we read exactly what the policy will
  produce at scan time, including any computed values.

Both are subprocess calls taking ~150ms for the whole directory, so results are
cached and invalidated on the directory's modification time. The policy editor
writes files and immediately re-reads them, so a stale cache here shows up as
the UI failing to reflect a save.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.actions import TIER_LABELS, SAFE_FALLBACK_ACTION, normalize_action, tier_of
from app.providers.opa.binary import OPA_SETUP_HINT, resolve_opa_binary

logger = logging.getLogger(__name__)

GOVERNANCE_PREFIX = "data.databricks.governance"

#: Packages that are libraries rather than policies.
NON_POLICY_PACKAGES = {"common"}

#: How long a single inspect/eval may take before we give up. These are local
#: subprocesses over a handful of small files; if one hangs, something is wrong
#: and blocking an API worker on it makes it worse.
_SUBPROCESS_TIMEOUT_SECONDS = 30


@dataclass
class RuleDescriptor:
    """One rule, as the UI and the agent see it."""

    rule: str
    id: str
    category: str
    severity: str
    description: str
    requested_action: str
    tier: int
    tier_label: str
    destructive: bool
    escalate_after_days: int = 0

    @property
    def is_above_notify(self) -> bool:
        """Tier 2 or higher. The safety suite asserts this implies ``destructive``."""
        return self.tier >= 2


@dataclass
class PolicyDescriptor:
    """One policy file, its package annotations, and its rules."""

    name: str
    package: str
    file: str
    title: str = ""
    description: str = ""
    owner: str = ""
    domain: str = ""
    resource_type: str = ""
    authors: List[str] = field(default_factory=list)
    rules: List[RuleDescriptor] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["rule_count"] = len(self.rules)
        data["max_tier"] = max((r.tier for r in self.rules), default=0)
        return data


class PolicyRegistryError(RuntimeError):
    """Raised when the policies could not be inspected at all."""


# --- Cache ------------------------------------------------------------------

_lock = threading.Lock()
_cache: Optional[List[PolicyDescriptor]] = None
_cache_signature: Optional[Tuple] = None


def _directory_signature(policies_dir: str) -> Tuple:
    """Cheap fingerprint of the directory: names and mtimes of every .rego file.

    Directory mtime alone is not enough — editing a file in place does not
    change it on every filesystem, and the policy editor does exactly that.
    """
    try:
        entries = []
        for name in sorted(os.listdir(policies_dir)):
            if not name.endswith(".rego"):
                continue
            path = os.path.join(policies_dir, name)
            stat = os.stat(path)
            entries.append((name, stat.st_mtime_ns, stat.st_size))
        return tuple(entries)
    except OSError:
        return ()


def invalidate_cache() -> None:
    """Drop the cache. Called after a policy is written through the API."""
    global _cache, _cache_signature
    with _lock:
        _cache = None
        _cache_signature = None


# --- OPA subprocess helpers -------------------------------------------------


def _run_opa(args: List[str]) -> str:
    exe = resolve_opa_binary()
    if not exe:
        raise PolicyRegistryError(OPA_SETUP_HINT)

    try:
        process = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise PolicyRegistryError(
            f"`opa {' '.join(args)}` did not finish within "
            f"{_SUBPROCESS_TIMEOUT_SECONDS}s."
        ) from e
    except FileNotFoundError as e:
        raise PolicyRegistryError(OPA_SETUP_HINT) from e

    if process.returncode != 0:
        raise PolicyRegistryError(
            f"`opa {' '.join(args)}` failed: {process.stderr or process.stdout}"
        )
    return process.stdout


def _inspect(policies_dir: str) -> Dict[str, Any]:
    raw = _run_opa(["inspect", "-a", "-f", "json", policies_dir])
    try:
        return json.loads(raw or "{}")
    except ValueError as e:
        raise PolicyRegistryError(f"Could not parse `opa inspect` output: {e}") from e


def _eval_rule_metadata(policies_dir: str) -> Dict[str, Any]:
    """Every package's ``rule_metadata``, keyed by package name.

    Packages without a ``rule_metadata`` rule simply do not appear, which is the
    correct handling for ``common`` and for any future library package.
    """
    query = (
        "{pkg: meta | "
        "some pkg; meta := data.databricks.governance[pkg].rule_metadata}"
    )
    raw = _run_opa(["eval", "-d", policies_dir, "-f", "values", query])
    try:
        parsed = json.loads(raw or "[]")
    except ValueError as e:
        raise PolicyRegistryError(f"Could not parse `opa eval` output: {e}") from e

    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else {}
    return parsed if isinstance(parsed, dict) else {}


# --- Parsing ----------------------------------------------------------------


def _package_short_name(package_path: str) -> str:
    """``data.databricks.governance.clusters`` -> ``clusters``."""
    if package_path.startswith(GOVERNANCE_PREFIX + "."):
        return package_path[len(GOVERNANCE_PREFIX) + 1:]
    return package_path.rsplit(".", 1)[-1]


def _annotation_index(inspection: Dict[str, Any]) -> Dict[str, dict]:
    """Package short name -> its package-scoped annotation block."""
    index: Dict[str, dict] = {}
    for entry in inspection.get("annotations", []) or []:
        annotations = entry.get("annotations") or {}
        if annotations.get("scope") != "package":
            continue
        package = entry.get("path") or annotations.get("package")
        if isinstance(package, list):
            # opa renders paths as term lists in some versions.
            package = ".".join(str(p.get("value", p)) for p in package)
        if not package:
            continue
        index[_package_short_name(str(package))] = annotations
    return index


def _authors(annotations: dict) -> List[str]:
    result = []
    for author in annotations.get("authors") or []:
        if isinstance(author, dict):
            name = author.get("name") or ""
            email = author.get("email") or ""
            result.append(f"{name} <{email}>".strip() if email and name else (name or email))
        elif isinstance(author, str):
            result.append(author)
    return [a for a in result if a]


def _rule_descriptor(rule_key: str, meta: Any) -> RuleDescriptor:
    """Build a descriptor, tolerating a rule whose metadata is malformed.

    A policy with a broken metadata block still needs to render in the editor —
    that is where somebody will go to fix it. Anything unreadable resolves to
    the safe fallback rather than raising.
    """
    if not isinstance(meta, dict):
        meta = {}

    requested = normalize_action(meta.get("requested_action")) or SAFE_FALLBACK_ACTION
    tier = tier_of(requested)

    def _text(key: str, default: str = "") -> str:
        value = meta.get(key, default)
        return value if isinstance(value, str) else default

    try:
        escalate = int(meta.get("escalate_after_days") or 0)
    except (TypeError, ValueError):
        escalate = 0

    return RuleDescriptor(
        rule=rule_key,
        id=_text("id", rule_key),
        category=_text("category", "control"),
        severity=_text("severity", "MEDIUM").upper(),
        description=_text("description"),
        requested_action=requested,
        tier=int(tier),
        tier_label=TIER_LABELS[tier],
        destructive=bool(meta.get("destructive", False)),
        escalate_after_days=escalate,
    )


def _build(policies_dir: str) -> List[PolicyDescriptor]:
    inspection = _inspect(policies_dir)
    annotations_by_package = _annotation_index(inspection)
    metadata_by_package = _eval_rule_metadata(policies_dir)

    descriptors: List[PolicyDescriptor] = []
    for package_path, files in (inspection.get("namespaces") or {}).items():
        short = _package_short_name(package_path)
        if short in NON_POLICY_PACKAGES:
            continue
        if not package_path.startswith(GOVERNANCE_PREFIX):
            continue

        annotations = annotations_by_package.get(short, {})
        custom = annotations.get("custom") or {}
        file_path = files[0] if files else ""

        rules = [
            _rule_descriptor(rule_key, meta)
            for rule_key, meta in sorted((metadata_by_package.get(short) or {}).items())
        ]

        descriptors.append(
            PolicyDescriptor(
                name=os.path.basename(file_path) or f"{short}.rego",
                package=short,
                file=file_path,
                title=annotations.get("title") or short.replace("_", " ").title(),
                description=(annotations.get("description") or "").strip(),
                owner=str(custom.get("owner") or ""),
                domain=str(custom.get("domain") or ""),
                resource_type=str(custom.get("resource_type") or ""),
                authors=_authors(annotations),
                rules=rules,
            )
        )

    descriptors.sort(key=lambda d: d.name)
    return descriptors


# --- Public API -------------------------------------------------------------


def load_policies(policies_dir: Optional[str] = None, *, force: bool = False) -> List[PolicyDescriptor]:
    """Every policy with its metadata. Cached until the files change."""
    global _cache, _cache_signature

    if policies_dir is None:
        from app.core.config import settings

        policies_dir = settings.get_policies_dir

    if not os.path.isdir(policies_dir):
        return []

    signature = _directory_signature(policies_dir)

    with _lock:
        if not force and _cache is not None and _cache_signature == signature:
            return _cache

    # Built outside the lock: the subprocess calls take long enough that holding
    # it would serialise every concurrent request behind one rebuild.
    built = _build(policies_dir)

    with _lock:
        _cache = built
        _cache_signature = signature

    return built


def get_policy(name: str, policies_dir: Optional[str] = None) -> Optional[PolicyDescriptor]:
    """Look up one policy by file name or package name."""
    from app.providers.opa.legacy_names import resolve_policy_name

    target = (name or "").strip()
    if target.endswith(".rego"):
        target = target[: -len(".rego")]

    candidates = resolve_policy_name(target)
    policies = load_policies(policies_dir)
    for candidate in candidates:
        for policy in policies:
            if policy.package == candidate or policy.name == f"{candidate}.rego":
                return policy
    return None


def all_rules(policies_dir: Optional[str] = None) -> List[Tuple[PolicyDescriptor, RuleDescriptor]]:
    """Flat (policy, rule) pairs. Used by the safety suite and the agent."""
    return [
        (policy, rule)
        for policy in load_policies(policies_dir)
        for rule in policy.rules
    ]


def registry_summary(policies_dir: Optional[str] = None) -> dict:
    """Counts for the dashboard header."""
    policies = load_policies(policies_dir)
    rules = [rule for policy in policies for rule in policy.rules]

    by_category: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    by_tier: Dict[str, int] = {}
    for rule in rules:
        by_category[rule.category] = by_category.get(rule.category, 0) + 1
        by_severity[rule.severity] = by_severity.get(rule.severity, 0) + 1
        by_tier[rule.tier_label] = by_tier.get(rule.tier_label, 0) + 1

    return {
        "policy_count": len(policies),
        "rule_count": len(rules),
        "by_category": by_category,
        "by_severity": by_severity,
        "by_tier": by_tier,
        "destructive_rule_count": sum(1 for r in rules if r.destructive),
        "max_tier": max((r.tier for r in rules), default=0),
    }
