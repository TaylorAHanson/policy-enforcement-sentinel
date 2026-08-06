import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ExternalLink,
  FilePlus2,
  FileText,
  GitPullRequest,
  Pencil,
  Search,
  Trash2,
} from "lucide-react";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { ConfirmPhraseDialog, Dialog } from "../components/ui/dialog";
import { Field, Input, Label, Select, Textarea } from "../components/ui/input";
import {
  Alert,
  EmptyState,
  ErrorState,
  SkeletonRows,
} from "../components/ui/feedback";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "../components/ui/table";
import { TierBadge } from "../components/safety/TierBadge";
import api, { type PolicyDashboard as Dashboard } from "../services/api";
import { usePolicyStore } from "../store/policyStore";
import { toast } from "../store/toastStore";

/**
 * The list of policies, and the place they are created, renamed and retired.
 *
 * This used to be a combobox in the editor's header — the only way to reach a
 * different policy was a control most people never found, sitting next to a
 * title that implied the page was about the one file already open. A dozen
 * policies is a collection, and a collection wants a list.
 *
 * Nothing here writes. Every mutation opens a pull request, including the ones
 * that read like direct manipulation: "New policy" produces an unsaved draft in
 * the editor, and rename and retire each open a PR. There is deliberately no
 * second path that reaches the policies directory.
 */
export default function PolicyDashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [retiring, setRetiring] = useState<string | null>(null);
  const [prUrl, setPrUrl] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.policies.dashboard());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!data) return [];
    if (!needle) return data.policies;
    return data.policies.filter((policy) =>
      [
        policy.name,
        policy.title,
        policy.resource_type,
        policy.domain,
        policy.owner,
        ...policy.rules.map((rule) => `${rule.id} ${rule.rule}`),
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [data, query]);

  // A policy whose resource type nothing discovers reports zero findings
  // forever, which reads exactly like a clean estate.
  const unscanned = useMemo(
    () =>
      (data?.policies ?? []).filter(
        (policy) =>
          policy.resource_type &&
          !data?.discovered_resource_types.includes(policy.resource_type),
      ),
    [data],
  );

  if (error && !data) {
    return <ErrorState message={error} onRetry={() => void load()} />;
  }

  const totalRules = data?.summary.rule_count ?? 0;

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-content">Policies</h1>
          <p className="mt-1 text-xs text-content-muted">
            {data
              ? `${data.policies.length} policies, ${totalRules} rules.`
              : "Loading…"}{" "}
            Policies live in git and change by pull request — creating,
            renaming and retiring one all open a PR rather than writing here.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative w-64">
            <Search
              className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-content-subtle"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search policies and rules"
              aria-label="Search policies"
              className="pl-8"
            />
          </div>
          <Button
            variant="primary"
            onClick={() => setCreating(true)}
            disabled={!data?.github_enabled}
            title={
              data?.github_enabled
                ? undefined
                : "GitHub is not configured, so a new policy could not be proposed."
            }
          >
            <FilePlus2 />
            New policy
          </Button>
        </div>
      </header>

      {data && !data.github_enabled && (
        <Alert tone="warning" title="Policies are read-only here">
          Policies are stored in git and changed by pull request, and GitHub is
          not configured for this deployment. Set <code>GITHUB_TOKEN</code> and{" "}
          <code>GITHUB_REPO</code> to propose changes.
        </Alert>
      )}

      {unscanned.length > 0 && (
        <Alert
          tone="warning"
          title={`${unscanned.length} ${
            unscanned.length === 1 ? "policy governs a" : "policies govern"
          } resource type nothing discovers`}
        >
          <p className="mb-1.5">
            {unscanned.map((p) => p.name.replace(/\.rego$/, "")).join(", ")}{" "}
            {unscanned.length === 1 ? "governs" : "govern"}{" "}
            {[...new Set(unscanned.map((p) => p.resource_type))].join(", ")}, and
            no handler collects{" "}
            {unscanned.length === 1 ? "that type" : "those types"}. Their rules
            never run against anything, so the zero in the findings column means
            nobody looked rather than nothing was wrong.
          </p>
          <p>
            Either a handler has to start discovering the type, or the policy is
            asserting something this system cannot check.
          </p>
        </Alert>
      )}

      {prUrl && (
        <Alert
          tone="success"
          title="Pull request opened"
          action={
            <a
              href={prUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-xs underline underline-offset-2"
            >
              Review it <ExternalLink className="size-3.5" />
            </a>
          }
        >
          Nothing changes in the estate until it is merged and the working copy
          syncs.
        </Alert>
      )}

      <Card className="overflow-hidden">
        {loading ? (
          <SkeletonRows rows={6} />
        ) : !visible.length ? (
          <EmptyState
            icon={<FileText className="size-6" />}
            title={query ? "No policy matches" : "No policies yet"}
            description={
              query
                ? "Nothing here matches that search, including rule IDs."
                : "A policy is a Rego file describing what good looks like for one resource type."
            }
            action={
              query ? (
                <Button variant="secondary" onClick={() => setQuery("")}>
                  Clear search
                </Button>
              ) : undefined
            }
          />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>Policy</TableHeaderCell>
                <TableHeaderCell>Governs</TableHeaderCell>
                <TableHeaderCell className="text-right">Rules</TableHeaderCell>
                <TableHeaderCell className="text-right">
                  Findings
                </TableHeaderCell>
                <TableHeaderCell>Last edit</TableHeaderCell>
                <TableHeaderCell className="text-right">Actions</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visible.map((policy) => (
                <PolicyRow
                  key={policy.name}
                  policy={policy}
                  findings={data?.findings_by_policy[policy.package]}
                  discovered={
                    !policy.resource_type ||
                    (data?.discovered_resource_types ?? []).includes(
                      policy.resource_type,
                    )
                  }
                  historyAvailable={data?.history_available ?? false}
                  githubEnabled={data?.github_enabled ?? false}
                  onEdit={() => navigate(`/policies/${policy.name}`)}
                  onRename={() => setRenaming(policy.name)}
                  onRetire={() => setRetiring(policy.name)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      {data?.latest_run && (
        <p className="text-2xs text-content-subtle">
          Findings are violations from the most recent scan (
          {data.latest_run.status}
          {data.latest_run.started_at
            ? `, ${new Date(data.latest_run.started_at).toLocaleString()}`
            : ""}
          ). A policy with none either found nothing or has no rule that can
          fire — the{" "}
          <Link to="/testing" className="underline underline-offset-2">
            Testing Center
          </Link>{" "}
          tells the two apart.
        </p>
      )}

      {creating && (
        <NewPolicyDialog
          onClose={() => setCreating(false)}
          onCreated={(name) => navigate(`/policies/${name}`)}
        />
      )}

      {renaming && (
        <RenameDialog
          policyName={renaming}
          onClose={() => setRenaming(null)}
          onRenamed={(url) => {
            setPrUrl(url);
            setRenaming(null);
            void load();
          }}
        />
      )}

      {retiring && (
        <RetireDialog
          policyName={retiring}
          onClose={() => setRetiring(null)}
          onRetired={(url) => {
            setPrUrl(url);
            setRetiring(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

function PolicyRow({
  policy,
  findings,
  discovered,
  historyAvailable,
  githubEnabled,
  onEdit,
  onRename,
  onRetire,
}: {
  policy: Dashboard["policies"][number];
  findings?: number;
  /** Whether a handler discovers this policy's resource type. */
  discovered: boolean;
  historyAvailable: boolean;
  githubEnabled: boolean;
  onEdit: () => void;
  onRename: () => void;
  onRetire: () => void;
}) {
  return (
    <TableRow interactive onClick={onEdit}>
      <TableCell>
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-content">
            {policy.name.replace(/\.rego$/, "")}
          </span>
          {policy.max_tier >= 2 && <TierBadge tier={policy.max_tier} showLabel={false} />}
          {policy.uncommitted_changes && (
            <Badge
              variant="warning"
              title="The file on disk differs from the last commit, and the file on disk is what a scan evaluates."
            >
              <AlertTriangle />
              uncommitted
            </Badge>
          )}
        </div>
        <p className="mt-0.5 line-clamp-1 text-2xs text-content-muted">
          {policy.title}
        </p>
      </TableCell>

      <TableCell>
        {policy.resource_type ? (
          <div className="flex items-center gap-1.5">
            <Badge variant="outline">{policy.resource_type}</Badge>
            {!discovered && (
              <Badge
                variant="warning"
                title={`Nothing discovers ${policy.resource_type}, so no resource of this type is ever evaluated. These rules cannot fire, and the zero beside them means "never looked" rather than "all clear".`}
              >
                <AlertTriangle />
                not scanned
              </Badge>
            )}
          </div>
        ) : (
          <span className="text-2xs text-content-subtle">—</span>
        )}
      </TableCell>

      <TableCell className="text-right tabular-nums">
        {policy.rule_count}
      </TableCell>

      <TableCell className="text-right tabular-nums">
        {findings ? (
          <Badge variant="danger">{findings}</Badge>
        ) : (
          <span className="text-2xs text-content-subtle">0</span>
        )}
      </TableCell>

      <TableCell>
        {policy.last_edit ? (
          <div className="min-w-0">
            <p className="truncate text-2xs text-content-muted">
              {policy.last_edit.subject}
            </p>
            <p className="text-2xs text-content-subtle">
              {policy.last_edit.author} ·{" "}
              {new Date(policy.last_edit.date).toLocaleDateString()}
            </p>
          </div>
        ) : (
          <span className="text-2xs text-content-subtle">
            {historyAvailable ? "—" : "No git checkout"}
          </span>
        )}
      </TableCell>

      <TableCell className="text-right">
        {/* The row itself opens the editor; these must not do it twice. */}
        <div
          className="flex items-center justify-end gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          <Button variant="secondary" size="sm" onClick={onEdit}>
            <Pencil />
            Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onRename}
            disabled={!githubEnabled}
            title="Rename this policy"
          >
            Rename
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onRetire}
            disabled={!githubEnabled}
            title="Retire this policy"
          >
            <Trash2 />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

/**
 * Creating a policy produces a draft, not a file.
 *
 * The scaffold comes back as text that lands in the editor unsaved, so the
 * route to a new policy is the same validate-then-PR path as any edit. A
 * separate "create" that wrote straight to the repository would be a second
 * way in, and the second way in is always the one that skips the checks.
 */
function NewPolicyDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (policyName: string) => void;
}) {
  const store = usePolicyStore();
  const [types, setTypes] = useState<
    { resource_type: string; suggested_name: string; already_governed: boolean }[]
  >([]);
  const [resourceType, setResourceType] = useState("");
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [owner, setOwner] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.policies
      .scaffoldDefaults()
      .then((d) => {
        setTypes(d.resource_types);
        const first = d.resource_types.find((t) => !t.already_governed) ?? d.resource_types[0];
        if (first) {
          setResourceType(first.resource_type);
          setName(first.suggested_name);
        }
      })
      .catch(() => setTypes([]));
  }, []);

  const pickType = (value: string) => {
    setResourceType(value);
    const match = types.find((t) => t.resource_type === value);
    if (match) setName(match.suggested_name);
  };

  const selected = types.find((t) => t.resource_type === resourceType);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.policies.scaffold({
        name,
        resource_type: resourceType,
        owner,
        title,
        description,
      });
      // Seed the editor's draft directly. The policy does not exist on the
      // branch yet, so selecting it by name would 404.
      store.startDraft(result.name, result.content);
      toast.success(
        "Draft created",
        "It exists only in this browser until you open a pull request.",
      );
      onCreated(result.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title="New policy"
      description="Starts from a working Tier 1 policy with one rule, so the first thing you edit is the rule rather than the scaffolding."
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            type="submit"
            form="new-policy-form"
            loading={busy}
            disabled={!name || !resourceType}
          >
            Create draft
          </Button>
        </>
      }
    >
      <form id="new-policy-form" onSubmit={create} className="space-y-4">
        {error && <Alert tone="danger">{error}</Alert>}

        <Field>
          <Label htmlFor="np-type">Resource type</Label>
          <Select
            id="np-type"
            value={resourceType}
            onChange={(e) => pickType(e.target.value)}
          >
            {types.map((type) => (
              <option key={type.resource_type} value={type.resource_type}>
                {type.resource_type}
                {type.already_governed ? " (already has a policy)" : ""}
              </option>
            ))}
          </Select>
          <p className="text-2xs text-content-subtle">
            Only types a handler discovers are listed. A policy for anything
            else would have no resources to evaluate.
          </p>
        </Field>

        {selected?.already_governed && (
          <Alert tone="info">
            <code>{resourceType}</code> already has a policy. A second one is
            allowed and its rules are evaluated too — worth being sure the rule
            you want does not belong in the existing file.
          </Alert>
        )}

        <Field>
          <Label htmlFor="np-name">File name</Label>
          <Input
            id="np-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="sql_warehouses"
            spellCheck={false}
          />
          <p className="text-2xs text-content-subtle">
            Becomes both <code>{name || "name"}.rego</code> and the Rego
            package, so lowercase letters, digits and underscores only.
          </p>
        </Field>

        <Field>
          <Label htmlFor="np-title">Title</Label>
          <Input
            id="np-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={`${resourceType || "Resource"} governance`}
          />
        </Field>

        <Field>
          <Label htmlFor="np-owner">Owner</Label>
          <Input
            id="np-owner"
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            placeholder="platform-governance"
          />
        </Field>

        <Field>
          <Label htmlFor="np-description">What is this policy for?</Label>
          <Textarea
            id="np-description"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What these rules cover and, more usefully, what they deliberately do not."
          />
        </Field>
      </form>
    </Dialog>
  );
}

function RenameDialog({
  policyName,
  onClose,
  onRenamed,
}: {
  policyName: string;
  onClose: () => void;
  onRenamed: (prUrl: string) => void;
}) {
  const current = policyName.replace(/\.rego$/, "");
  const [name, setName] = useState(current);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.policies.rename(policyName, name);
      onRenamed(result.pr_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Rename ${current}`}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            type="submit"
            form="rename-form"
            loading={busy}
            disabled={!name || name === current}
          >
            <GitPullRequest />
            Open rename PR
          </Button>
        </>
      }
    >
      <form id="rename-form" onSubmit={submit} className="space-y-4">
        {error && <Alert tone="danger">{error}</Alert>}

        <Field>
          <Label htmlFor="rn-name">New name</Label>
          <Input
            id="rn-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            spellCheck={false}
            autoFocus
          />
        </Field>

        <Alert tone="info" title="What the pull request will contain">
          <p className="mb-1.5">
            A rename is not just a file move. Three things change together:
          </p>
          <ul className="list-disc space-y-1 pl-4">
            <li>
              the file becomes <code>{name || "new_name"}.rego</code>
            </li>
            <li>
              its Rego package is rewritten to match, because OPA resolves rules
              by package and a mismatch would leave the policy loaded under the
              old name
            </li>
            <li>
              <code>{current}</code> is recorded in the policy's{" "}
              <code>replaces</code> metadata, so allowlist exceptions and saved
              filters naming the old spelling keep resolving
            </li>
          </ul>
          <p className="mt-1.5">
            Rule IDs do not change, so anything referencing a rule directly is
            unaffected.
          </p>
        </Alert>
      </form>
    </Dialog>
  );
}

function RetireDialog({
  policyName,
  onClose,
  onRetired,
}: {
  policyName: string;
  onClose: () => void;
  onRetired: (prUrl: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const current = policyName.replace(/\.rego$/, "");

  const confirm = async () => {
    setBusy(true);
    try {
      const result = await api.policies.remove(policyName);
      onRetired(result.pr_url);
    } catch (err) {
      toast.error(
        "Could not open the retire PR",
        err instanceof Error ? err.message : String(err),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmPhraseDialog
      open
      onClose={onClose}
      onConfirm={confirm}
      title={`Retire ${current}`}
      phrase={current}
      confirmLabel="Open retire PR"
      loading={busy}
    >
      <p>
        Opens a pull request deleting this policy. Once merged, its rules stop
        being evaluated and every resource they were flagging disappears from
        scan results — which looks identical to the estate having been fixed.
      </p>
    </ConfirmPhraseDialog>
  );
}
