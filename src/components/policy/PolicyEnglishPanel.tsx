import { useEffect, useState } from "react";
import { Languages, RefreshCw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "../ui/button";
import { EmptyState, ErrorState, Skeleton } from "../ui/feedback";
import api from "../../services/api";

/**
 * A plain-English reading of the policy, produced by the agent.
 *
 * Rego is precise and almost nobody outside the platform team can read it,
 * which makes policy review a bottleneck of one or two people. This panel is
 * for the data owner who needs to agree that a rule says what the team claims
 * it says.
 *
 * It is explicitly a *reading* and not a source of truth. The Rego is what
 * runs, and the panel says so, because an LLM paraphrase that quietly drops a
 * condition would otherwise look authoritative.
 *
 * Generating here stores nothing. The explanation reaches the repository by
 * being committed alongside the policy when a pull request is opened, so what
 * a reviewer reads is always the version that shipped with that Rego.
 */
export function PolicyEnglishPanel({
  policyName,
  content,
}: {
  policyName: string;
  content: string;
}) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [explainedContent, setExplainedContent] = useState<string | null>(null);
  const [fromCommit, setFromCommit] = useState(false);

  const explain = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.agent.explain({
        content,
        policy_name: policyName,
      });
      setExplanation(result.explanation);
      setExplainedContent(content);
      setFromCommit(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  // The committed sibling `.md` is free and already reviewed, so it is what
  // gets shown first. Generating is the fallback, and the button.
  useEffect(() => {
    let cancelled = false;
    setExplanation(null);
    setExplainedContent(null);
    setError(null);
    setFromCommit(false);

    void api.agent
      .committedExplanation(policyName)
      .then((result) => {
        if (cancelled || !result.exists || !result.explanation) return;
        setExplanation(result.explanation);
        setExplainedContent(content);
        setFromCommit(true);
      })
      .catch(() => {
        /* No committed explanation is the normal case for a new policy. */
      });

    return () => {
      cancelled = true;
    };
    // Deliberately not keyed on `content`: refetching on every keystroke would
    // replace what the user is reading with the committed version mid-edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [policyName]);

  const stale = explanation != null && explainedContent !== content;

  if (loading) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-11/12" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <ErrorState message={error} onRetry={() => void explain()} />
      </div>
    );
  }

  if (!explanation) {
    return (
      <EmptyState
        icon={<Languages className="size-8" />}
        title="Explain this policy in plain English"
        description="Ask the agent to describe what this policy checks, which resources it applies to, and what it asks for when a rule fails. Useful for review with people who do not read Rego."
        action={
          <Button variant="primary" onClick={() => void explain()}>
            <Languages />
            Explain
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-2xs text-content-subtle">
          {fromCommit
            ? `The committed ${policyName.replace(/\.rego$/, "")}.md, which was reviewed alongside the policy.`
            : "Generated from the current editor contents. Opening a PR commits a fresh one next to the policy."}{" "}
          The Rego is what runs — treat this as a reading of it, not a substitute.
        </p>
        <Button variant="ghost" size="sm" onClick={() => void explain()}>
          <RefreshCw />
          Regenerate
        </Button>
      </div>

      {stale && (
        <p className="rounded border border-warning/30 bg-warning-subtle px-3 py-1.5 text-2xs text-warning">
          The policy has changed since this was generated.
        </p>
      )}

      <div className="prose-sentinel text-xs">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{explanation}</ReactMarkdown>
      </div>
    </div>
  );
}
