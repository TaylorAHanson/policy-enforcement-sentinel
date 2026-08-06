import { DiffEditor } from "@monaco-editor/react";
import { ShieldAlert } from "lucide-react";

import type { AuthoredPolicy } from "../../services/api";
import { Badge, Button } from "../ui";
import { TierBadge } from "../safety/TierBadge";

const DIFF_OPTIONS = {
  // Inline rather than side by side. The panel is one column of a three-column
  // page, and side-by-side at that width gives two unreadable gutters.
  renderSideBySide: false,
  readOnly: true,
  minimap: { enabled: false },
  fontSize: 12,
  lineNumbers: "off" as const,
  scrollBeyondLastLine: false,
  renderOverviewRuler: false,
  scrollbar: { alwaysConsumeMouseWheel: false },
  folding: false,
};

/** Roughly the height of the change, capped so a rewrite cannot fill the pane. */
function diffHeight(original: string, modified: string): number {
  const lines = Math.max(original.split("\n").length, modified.split("\n").length);
  return Math.min(Math.max(lines * 18 + 16, 120), 420);
}

/**
 * A proposed policy, shown as a diff against what the editor has open.
 *
 * The previous draft box was a `<pre>` of the whole generated file, which meant
 * reading several hundred lines to find the four that changed — and the change
 * is the only part anyone needs to review. A diff also makes an accidental
 * deletion visible, which is the failure mode that matters when a model returns
 * "the whole file with your change applied" and quietly drops a rule.
 */
export function ProposalDiff({
  proposal,
  original,
  onApply,
  onDismiss,
}: {
  proposal: AuthoredPolicy;
  original: string;
  onApply: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="mt-3 space-y-2 rounded-md border border-border bg-surface-raised p-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="font-mono">
          {proposal.policy_name}
        </Badge>
        {proposal.is_new_file && <Badge variant="info">new file</Badge>}
        <TierBadge tier={proposal.max_tier} />
        {proposal.valid ? (
          <Badge variant="success">compiles</Badge>
        ) : (
          <Badge variant="danger">does not compile</Badge>
        )}
        {proposal.attempts > 1 && (
          <span className="text-2xs text-content-subtle">
            {proposal.attempts} attempts
          </span>
        )}
      </div>

      {!proposal.valid && proposal.validation_errors.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-2xs text-danger">
          {proposal.validation_errors.map((error, i) => (
            <li key={i} className="font-mono">
              {error}
            </li>
          ))}
        </ul>
      )}

      <div
        className="overflow-hidden rounded border border-border"
        style={{ height: diffHeight(original, proposal.content) }}
      >
        <DiffEditor
          height="100%"
          language="rego"
          theme="vs-dark"
          original={original}
          modified={proposal.content}
          options={DIFF_OPTIONS}
        />
      </div>

      <div className="flex items-center gap-2">
        <Button variant="primary" size="sm" onClick={onApply}>
          Apply to the editor
        </Button>
        <Button variant="ghost" size="sm" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>

      <p className="text-2xs text-content-subtle">
        Nothing has been written. Applying puts it in the editor, where you try
        it in the playground and open a pull request.
      </p>
    </div>
  );
}

/** The tier ceiling refusing a change, with what to do instead. */
export function ProposalRefusal({
  violations,
  remedy,
}: {
  violations: string[];
  remedy: string;
}) {
  return (
    <div className="mt-3 space-y-2 rounded-md border border-danger/50 bg-danger-subtle p-2.5 text-2xs text-danger">
      <p className="font-medium">
        The change was withdrawn: it asks for more than the assistant may write.
      </p>
      <ul className="list-disc space-y-0.5 pl-4">
        {violations.map((violation, i) => (
          <li key={i}>{violation}</li>
        ))}
      </ul>
      <p className="flex items-start gap-1.5">
        <ShieldAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
        {remedy}
      </p>
    </div>
  );
}
