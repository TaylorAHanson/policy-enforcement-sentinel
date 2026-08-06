import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "../ui/button";
import { ErrorState, Skeleton } from "../ui/feedback";
import api from "../../services/api";

/** How long to let typing settle before spending a generation on it. */
const DEBOUNCE_MS = 1500;

/**
 * Explanations already seen in this session, keyed by the content they explain.
 *
 * The panel unmounts every time the user leaves the tab, so without this a tab
 * switch and a switch back would be a round trip for something already on the
 * screen a second ago. The server caches too, on the same key; this saves the
 * request rather than the generation.
 */
const seen = new Map<string, string>();

/**
 * A plain-English reading of the policy, produced by the agent.
 *
 * Rego is precise and almost nobody outside the platform team can read it,
 * which makes policy review a bottleneck of one or two people. This panel is
 * for the data owner who needs to agree that a rule says what the team claims
 * it says.
 *
 * It generates itself rather than waiting behind a button. An explanation that
 * someone forgot to regenerate is worse than none at all: it is confidently
 * about a policy that no longer exists, and it looks exactly as authoritative
 * as one that is current. The cost that made a button reasonable is handled by
 * caching on a hash of the content, on both sides.
 *
 * It remains a *reading* and not a source of truth. The Rego is what runs, and
 * the panel says so, because an LLM paraphrase that quietly drops a condition
 * would otherwise look authoritative.
 */
export function PolicyEnglishPanel({
  policyName,
  content,
  committedContent,
}: {
  policyName: string;
  content: string;
  /** What is committed in git. Used to decide whether the reviewed `.md` fits. */
  committedContent: string;
}) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromCommit, setFromCommit] = useState(false);
  /** What the text on screen actually explains, so staleness can be honest. */
  const [explains, setExplains] = useState<string | null>(null);

  // Read in effects that must not re-run when the editor content changes.
  const contentRef = useRef(content);
  contentRef.current = content;

  const generate = async (source: string, { force = false } = {}) => {
    const cached = seen.get(source);
    if (cached && !force) {
      setExplanation(cached);
      setExplains(source);
      setFromCommit(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const result = await api.agent.explain({
        content: source,
        policy_name: policyName,
      });
      // The editor may have moved on while this was in flight. Storing the
      // result keyed by what it explains means the next debounce tick finds it
      // rather than paying for it again.
      seen.set(source, result.explanation);
      if (contentRef.current !== source) return;

      setExplanation(result.explanation);
      setExplains(source);
      setFromCommit(false);
    } catch (e) {
      if (contentRef.current !== source) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  // A different policy is a clean slate. The committed sibling `.md` is free
  // and was reviewed alongside the Rego, so it is preferred — but only when the
  // editor still holds what was committed. Showing it against an edited draft
  // is the bug this replaces: it described the file on the branch while the
  // user read it as describing what was in front of them.
  useEffect(() => {
    let cancelled = false;
    setExplanation(null);
    setExplains(null);
    setError(null);
    setFromCommit(false);

    void api.agent
      .committedExplanation(policyName)
      .then((result) => {
        if (cancelled || !result.exists || !result.explanation) return;
        if (contentRef.current !== committedContent) return;

        setExplanation(result.explanation);
        setExplains(committedContent);
        setFromCommit(true);
      })
      .catch(() => {
        /* No committed explanation is the normal case for a new policy. */
      });

    return () => {
      cancelled = true;
    };
    // Keyed on the policy alone. Re-running on every keystroke would replace
    // what the user is reading with the committed version mid-edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [policyName]);

  // Generate whatever is on screen but not yet explained, once typing settles.
  useEffect(() => {
    if (!content.trim()) return;
    if (explains === content) return;
    if (error) return;

    const timer = window.setTimeout(() => {
      void generate(content);
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, explains, error, policyName]);

  if (error) {
    return (
      <div className="p-4">
        <ErrorState message={error} onRetry={() => void generate(content, { force: true })} />
      </div>
    );
  }

  if (loading && !explanation) {
    return (
      <div className="space-y-3 p-4">
        <p className="text-2xs text-content-subtle">
          Reading {policyName} and writing it out in plain English.
        </p>
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-11/12" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    );
  }

  if (!explanation) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    );
  }

  const stale = explains !== content;

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-2xs text-content-subtle">
          {fromCommit
            ? `The committed ${policyName.replace(/\.rego$/, "")}.md, which was reviewed alongside the policy.`
            : "Generated from the editor contents, and regenerated when they change. Opening a PR commits a fresh one next to the policy."}{" "}
          The Rego is what runs — treat this as a reading of it, not a substitute.
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void generate(content, { force: true })}
          loading={loading}
          disabled={loading}
        >
          <RefreshCw />
          Regenerate
        </Button>
      </div>

      {stale && (
        <p className="rounded border border-warning/30 bg-warning-subtle px-3 py-1.5 text-2xs text-warning">
          {loading
            ? "The policy has changed. Rewriting this now."
            : "The policy has changed since this was written. A new reading is on its way."}
        </p>
      )}

      <div className="prose-sentinel text-xs">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{explanation}</ReactMarkdown>
      </div>
    </div>
  );
}
