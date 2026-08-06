import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "../ui/badge";
import { Alert } from "../ui/feedback";
import { cn } from "../../lib/utils";
import type { DriftFinding, DriftReport } from "../../services/api";

/**
 * Whether the field catalogue is telling the truth about the estate.
 *
 * Every other panel on this page is checked *against* `discovered_fields`. The
 * coverage report calls a rule healthy because the catalogue says its field is
 * collected; fixtures are refused if they use a field outside it. So a wrong
 * catalogue does not produce an error anywhere — it produces confident green
 * results, which is the failure this whole page exists to prevent, one level
 * further down.
 *
 * This is the only check that runs the other way, and it needs a real scan.
 * Against fixtures it would only confirm that fixtures were written to match
 * the catalogue, which is true by construction and worth nothing.
 */

const KIND_LABEL: Record<string, string> = {
  never_emitted: "Declared but never collected",
  undeclared: "Collected but never declared",
  impossible_comparison: "Compared against a value that never occurs",
};

/**
 * Worst first. A field declared and never collected is the dangerous one: the
 * coverage report reads the declaration, believes the field is available, and
 * reports every rule using it as working.
 */
const KIND_ORDER = ["never_emitted", "impossible_comparison", "undeclared"];

export function CatalogueDrift({ drift }: { drift: DriftReport }) {
  if (!drift.available) {
    return (
      <Alert tone="info" title="The field catalogue has not been checked yet">
        {drift.reason}
      </Alert>
    );
  }

  const scanned = drift.resource_types.filter((entry) => entry.scanned);

  if (!drift.total) {
    return (
      <Alert tone="success" title="The field catalogue matches the estate">
        Every field the handlers declare was collected on the last scan, and no
        rule compares a field against a value your estate never produces. Checked
        against {scanned.length} resource type
        {scanned.length === 1 ? "" : "s"}.
      </Alert>
    );
  }

  const grouped = KIND_ORDER.map((kind) => ({
    kind,
    findings: drift.findings.filter((finding) => finding.kind === kind),
  })).filter((group) => group.findings.length > 0);

  return (
    <Alert
      tone="danger"
      title={`${drift.total} place${drift.total === 1 ? "" : "s"} where the field catalogue and your estate disagree`}
    >
      <p className="mb-3">
        The catalogue is what every other check on this page trusts. A rule
        reading a field that is declared but never collected cannot fire, and the
        coverage report above will still count it as working &mdash; because it
        reads the same declaration.
      </p>

      <div className="space-y-1.5">
        {grouped.map((group) => (
          <DriftGroup
            key={group.kind}
            kind={group.kind}
            findings={group.findings}
          />
        ))}
      </div>

      {drift.inert.length > 0 && <Inert findings={drift.inert} />}
    </Alert>
  );
}

function DriftGroup({
  kind,
  findings,
}: {
  kind: string;
  findings: DriftFinding[];
}) {
  const [open, setOpen] = useState(kind === "never_emitted");
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 rounded px-1 py-1 text-left hover:bg-surface-hover"
      >
        <Chevron className="h-3.5 w-3.5 shrink-0 text-content-muted" />
        <span
          className={cn(
            "font-medium",
            kind === "undeclared" ? "text-warning" : "text-danger",
          )}
        >
          {KIND_LABEL[kind] ?? kind}
        </span>
        <Badge variant="outline">{findings.length}</Badge>
      </button>

      {open && (
        <ul className="ml-6 mt-1 space-y-2">
          {findings.map((finding) => (
            <li
              key={`${finding.resource_type}.${finding.field}.${finding.policy ?? ""}`}
              className="text-sm"
            >
              <code className="text-xs">
                {finding.resource_type}.{finding.field}
              </code>
              <p className="mt-0.5 text-content-muted">{finding.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Fields that are declared, collected, and empty on everything.
 *
 * Kept apart from the findings above on purpose. A nullable field on a feature
 * nobody uses looks exactly like a collector that has broken, and nothing in the
 * data distinguishes them — so this says only what is certain, which is that no
 * rule reading these can fire against the estate as it stands.
 */
function Inert({ findings }: { findings: DriftFinding[] }) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="mt-3 border-t border-border pt-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 rounded px-1 py-1 text-left hover:bg-surface-hover"
      >
        <Chevron className="h-3.5 w-3.5 shrink-0 text-content-muted" />
        <span className="text-content-muted">
          {findings.length} field{findings.length === 1 ? " is" : "s are"} empty
          on every resource
        </span>
      </button>

      {open && (
        <div className="ml-6 mt-1">
          <p className="mb-2 text-sm text-content-muted">
            No rule reading these can fire against your estate today. That may be
            entirely correct &mdash; a nullable setting on a feature nobody uses
            looks the same from here as a collector that has stopped working.
          </p>
          <ul className="space-y-1">
            {findings.map((finding) => (
              <li key={`${finding.resource_type}.${finding.field}`}>
                <code className="text-xs">
                  {finding.resource_type}.{finding.field}
                </code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
