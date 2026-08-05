import { useEffect, useRef, useState } from "react";

import { useAgentStore } from "../../store";
import { cn } from "../../lib/utils";
import { Alert, Badge, Button, EmptyState, Spinner } from "../ui";

/** Starting points, so the panel is not an empty box with a cursor in it. */
const SUGGESTIONS = [
  "Which policies would affect my production clusters?",
  "What did the last scan find, by severity?",
  "Would anything actually be enforced right now?",
  "Which rules have no findings at all?",
];

interface Props {
  className?: string;
  /** Rendered above the transcript, e.g. the policy the editor has open. */
  contextNote?: string;
}

/**
 * Q&A over the deployment.
 *
 * The tools behind this are read-only by construction, and the panel says so:
 * an assistant that can see every policy and finding invites the assumption
 * that it can also change them.
 */
export function AgentChatPanel({ className, contextNote }: Props) {
  const { status, statusLoaded, messages, asking, loadStatus, ask, clearChat } =
    useAgentStore();
  const [draft, setDraft] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!statusLoaded) void loadStatus();
  }, [statusLoaded, loadStatus]);

  useEffect(() => {
    // Pin to the newest message. Without this a long answer scrolls the
    // question out of view and leaves the user looking at its middle.
    const node = transcriptRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, asking]);

  const submit = (question: string) => {
    if (!question.trim() || asking) return;
    setDraft("");
    void ask(question);
  };

  if (statusLoaded && (!status || !status.enabled || !status.configured)) {
    return (
      <Alert tone="info" title="The policy assistant is not available">
        {status && !status.enabled
          ? "It is switched off in Settings."
          : "No model is configured. Set the AI Gateway model in Settings to turn it on."}
      </Alert>
    );
  }

  return (
    <div className={cn("flex h-full min-h-0 flex-col gap-3", className)}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Badge variant="info">Read-only</Badge>
          <span className="text-xs text-content-muted">
            The assistant can read policies and findings. It cannot change or act
            on anything.
          </span>
        </div>
        {messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={clearChat}>
            Clear
          </Button>
        )}
      </div>

      {contextNote && (
        <p className="text-xs text-content-muted">Context: {contextNote}</p>
      )}

      <div
        ref={transcriptRef}
        className="min-h-0 flex-1 space-y-4 overflow-y-auto rounded-md border border-border bg-surface-sunken p-4"
      >
        {messages.length === 0 && !asking ? (
          <EmptyState
            title="Ask about your policies"
            description="Answers come from the live policy registry and the most recent scan, not from memory."
            action={
              <div className="flex flex-col gap-2">
                {SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => submit(suggestion)}
                    className="rounded-md border border-border px-3 py-2 text-left text-2xs text-content-muted transition-colors hover:border-accent hover:text-content"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            }
          />
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={cn(
                "rounded-md px-3 py-2 text-sm",
                message.role === "user"
                  ? "ml-8 bg-surface-raised text-content"
                  : "mr-8 border border-border bg-surface text-content-muted",
                message.failed && "border-danger/50 text-danger",
              )}
            >
              <p className="whitespace-pre-wrap leading-relaxed">
                {message.content}
              </p>

              {message.toolCalls && message.toolCalls.length > 0 && (
                <details className="mt-3 border-t border-border pt-2">
                  <summary className="cursor-pointer text-xs text-content-subtle">
                    Looked at {message.toolCalls.length}{" "}
                    {message.toolCalls.length === 1 ? "source" : "sources"}
                  </summary>
                  <ul className="mt-2 space-y-1">
                    {message.toolCalls.map((call, index) => (
                      <li
                        key={`${call.tool}-${index}`}
                        className="font-mono text-xs text-content-subtle"
                      >
                        {call.tool}
                        {call.error ? ` — failed: ${call.error}` : ""}
                      </li>
                    ))}
                  </ul>
                </details>
              )}

              {message.truncated && (
                <p className="mt-2 text-xs text-warning">
                  Stopped at the tool-call limit, so this answer may be
                  incomplete. Try a narrower question.
                </p>
              )}
            </div>
          ))
        )}

        {asking && (
          <div className="mr-8 flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm text-content-muted">
            <Spinner className="size-3" />
            Looking that up
          </div>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit(draft);
        }}
        className="flex gap-2"
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask about a policy, a finding, or what would be enforced"
          disabled={asking}
          className="flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm text-content placeholder:text-content-subtle focus:border-brand focus:outline-none disabled:opacity-60"
        />
        <Button type="submit" disabled={!draft.trim() || asking} loading={asking}>
          Ask
        </Button>
      </form>
    </div>
  );
}
