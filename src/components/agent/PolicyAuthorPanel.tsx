import { useState } from "react";
import { ShieldAlert, Sparkles } from "lucide-react";

import { useAgentStore } from "../../store";
import { Alert, Badge, Button, Spinner } from "../ui";
import { TierBadge } from "../safety/TierBadge";

interface Props {
  /** The policy the editor has open, if any. Scopes the request to that file. */
  policyName?: string;
  currentContent?: string;
  /** Replaces the editor's contents with the draft. The user still saves it. */
  onApply: (content: string, policyName: string) => void;
}

/**
 * Describe a rule; get Rego back.
 *
 * The draft is never written. It lands in the editor, where the user reads it,
 * runs it against the playground, and saves it themselves — an LLM writing
 * straight to a policy file would put generated text into the enforcement path
 * without anyone having read it.
 *
 * The tier ceiling is a server-side check on the generated text, not a prompt
 * instruction. When it fires, this panel explains what to do by hand instead.
 */
export function PolicyAuthorPanel({ policyName, currentContent, onApply }: Props) {
  const {
    author,
    authoring,
    proposal,
    guardrailViolations,
    guardrailRemedy,
    dismissProposal,
  } = useAgentStore();
  const [instruction, setInstruction] = useState("");
  const [scoped, setScoped] = useState(true);

  const submit = async () => {
    if (!instruction.trim()) return;
    await author(instruction, {
      targetPolicy: scoped ? policyName : undefined,
      existingContent: scoped ? currentContent : undefined,
    });
  };

  return (
    <div className="space-y-3 p-3">
      <p className="text-2xs text-content-subtle">
        Describe the rule in plain language. The assistant writes to the file
        conventions and validates with <code>opa check</code> before returning
        anything.
      </p>

      <textarea
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        placeholder="Warn when a SQL warehouse in production has no auto-stop set"
        rows={4}
        className="w-full resize-none rounded-md border border-border-strong bg-surface-raised px-2.5 py-2 text-2xs leading-relaxed text-content placeholder:text-content-subtle"
      />

      {policyName && (
        <label className="flex items-center gap-2 text-2xs text-content-muted">
          <input
            type="checkbox"
            checked={scoped}
            onChange={(e) => setScoped(e.target.checked)}
            className="size-3 accent-accent"
          />
          Add it to {policyName}
        </label>
      )}

      <Button
        variant="primary"
        size="sm"
        onClick={() => void submit()}
        loading={authoring}
        disabled={!instruction.trim() || authoring}
      >
        <Sparkles />
        Draft the rule
      </Button>

      {authoring && (
        <p className="flex items-center gap-2 text-2xs text-content-subtle">
          <Spinner className="size-3" />
          Writing and validating. This takes a few seconds.
        </p>
      )}

      {guardrailViolations.length > 0 && (
        <Alert tone="danger" title="Refused: this asks for more than the assistant may write">
          <ul className="list-disc space-y-0.5 pl-4">
            {guardrailViolations.map((violation, i) => (
              <li key={i}>{violation}</li>
            ))}
          </ul>
          <p className="mt-2 flex items-start gap-1.5">
            <ShieldAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
            {guardrailRemedy}
          </p>
        </Alert>
      )}

      {proposal && (
        <div className="space-y-2 rounded-md border border-border bg-surface-raised p-2.5">
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

          <pre className="max-h-60 overflow-auto rounded border border-border bg-canvas px-2.5 py-2 font-mono text-2xs leading-relaxed text-content-muted">
            {proposal.content}
          </pre>

          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                onApply(proposal.content, proposal.policy_name);
                dismissProposal();
              }}
            >
              Load into the editor
            </Button>
            <Button variant="ghost" size="sm" onClick={dismissProposal}>
              Discard
            </Button>
          </div>

          <p className="text-2xs text-content-subtle">
            Nothing has been written. Review it, try it in the playground, then
            save.
          </p>
        </div>
      )}
    </div>
  );
}
