import { useEffect, useMemo, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { useAgentStore } from "../../store";
import { cn } from "../../lib/utils";
import { Alert, Badge, Button, EmptyState, Spinner } from "../ui";
import { ProposalDiff, ProposalRefusal } from "./ProposalDiff";

/** Starting points, so the panel is not an empty box with a cursor in it. */
const GENERAL_SUGGESTIONS = [
  "Which policies would affect my production clusters?",
  "What did the last scan find, by severity?",
  "Would anything actually be enforced right now?",
];

const POLICY_SUGGESTIONS = [
  "What does this policy do, in plain terms?",
  "Which resources would this flag today?",
  "Add a rule requiring an owner tag",
];

interface Props {
  className?: string;
  /** The policy the editor has open. Context for answers, and the diff base. */
  policyName?: string;
  currentContent?: string;
  /** Replaces the editor's contents with a proposal. The user still opens the PR. */
  onApply?: (content: string, policyName: string) => void;
}

/**
 * One conversation that answers questions and proposes edits.
 *
 * This replaces a split between a Q&A tab and a one-shot code generator whose
 * prompt forbade prose, so that asking it a question got you a policy file. The
 * two were the same conversation to everyone except the code, and joining them
 * up means a user can ask why a rule fires and then ask to change it without
 * moving tabs or repeating the context.
 *
 * The tools behind this are read-only by construction, and a proposal is a
 * proposal: it lands in the editor for a human to read, try, and put through a
 * pull request. Nothing here writes.
 */
export function AgentPanel({
  className,
  policyName,
  currentContent,
  onApply,
}: Props) {
  const {
    status,
    statusLoaded,
    messages,
    asking,
    loadStatus,
    send,
    resolveProposal,
    clearChat,
    composerDraft: draft,
    setComposerDraft: setDraft,
  } = useAgentStore();
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

  const suggestions = useMemo(
    () => (policyName ? POLICY_SUGGESTIONS : GENERAL_SUGGESTIONS),
    [policyName],
  );

  const submit = (message: string) => {
    if (!message.trim() || asking) return;
    setDraft("");
    void send(message, {
      targetPolicy: policyName,
      openContent: currentContent,
    });
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
          <Badge variant="info">Proposes, never applies</Badge>
          <span className="text-2xs text-content-muted">
            {policyName
              ? `Reading ${policyName}. Changes come back as a diff you approve.`
              : "The assistant can read policies and findings. It cannot act on anything."}
          </span>
        </div>
        {messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={clearChat}>
            Clear
          </Button>
        )}
      </div>

      <div
        ref={transcriptRef}
        className="min-h-0 flex-1 space-y-4 overflow-y-auto rounded-md border border-border bg-surface-sunken p-4"
      >
        {messages.length === 0 && !asking ? (
          <EmptyState
            title="Ask, or describe a change"
            description="Answers come from the live policy registry and the most recent scan. Ask for a change and it comes back as a diff."
            action={
              <div className="flex flex-col gap-2">
                {suggestions.map((suggestion) => (
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
                  : "border border-border bg-surface text-content-muted",
                message.failed && "border-danger/50 text-danger",
              )}
            >
              {message.role === "assistant" ? (
                <div className="prose-sentinel text-xs">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {message.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap leading-relaxed">
                  {message.content}
                </p>
              )}

              {message.refusal && (
                <ProposalRefusal
                  violations={message.refusal.violations}
                  remedy={message.refusal.remedy}
                />
              )}

              {message.fieldWarnings?.length ? (
                <Alert
                  tone="warning"
                  title="This would compile, and never fire"
                  className="mt-2"
                >
                  <p className="mb-1.5">
                    Rego treats a reference to data that was never collected as
                    simply not matching, so a rule built on{" "}
                    {message.fieldWarnings.length === 1 ? "this field" : "these fields"}{" "}
                    reports every resource as compliant — indefinitely, and
                    without any error to notice.
                  </p>
                  <ul className="space-y-1">
                    {message.fieldWarnings.map((warning) => (
                      <li key={warning.field} className="text-2xs">
                        <code className="font-mono">
                          input.resource.{warning.field}
                        </code>{" "}
                        is not collected for {warning.resource_type}.
                      </li>
                    ))}
                  </ul>
                  <p className="mt-1.5 text-2xs">
                    The handler for that resource type has to collect the field
                    during discovery before any policy can test it.
                  </p>
                </Alert>
              ) : null}

              {message.proposal && !message.resolved && (
                <ProposalDiff
                  proposal={message.proposal}
                  original={
                    message.proposal.is_new_file ? "" : (currentContent ?? "")
                  }
                  onApply={() => {
                    onApply?.(
                      message.proposal!.content,
                      message.proposal!.policy_name,
                    );
                    resolveProposal(message.id);
                  }}
                  onDismiss={() => resolveProposal(message.id)}
                />
              )}

              {message.proposal && message.resolved && (
                <p className="mt-2 text-2xs text-content-subtle">
                  Proposal for {message.proposal.policy_name} closed.
                </p>
              )}

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
          <div className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 text-sm text-content-muted">
            <Spinner className="size-3" />
            Looking that up
          </div>
        )}
      </div>

      <AgentComposer
        value={draft}
        onChange={setDraft}
        onSubmit={() => submit(draft)}
        busy={asking}
        scopedTo={policyName}
      />
    </div>
  );
}

/**
 * The message box.
 *
 * Enter still sends, because that is what this input did before and people have
 * the habit. Shift+Enter and Cmd/Ctrl+Enter are the additions: the first makes
 * a multi-line request possible at all, and the second is the shortcut people
 * arrive with from every other assistant, where Enter is a newline.
 */
function AgentComposer({
  value,
  onChange,
  onSubmit,
  busy,
  scopedTo,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  busy: boolean;
  scopedTo?: string;
}) {
  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter") return;
    // Shift+Enter is the only Enter that does not send. Ctrl/Cmd+Enter falls
    // through to the same path deliberately, so the shortcut works without
    // needing its own branch.
    if (event.shiftKey) return;
    event.preventDefault();
    onSubmit();
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-end gap-2">
        <textarea
          value={value}
          rows={2}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={
            scopedTo
              ? "Ask about this policy, or describe a change"
              : "Ask about a policy, a finding, or what would be enforced"
          }
          disabled={busy}
          className="max-h-40 min-h-[3.5rem] flex-1 resize-y rounded-md border border-border bg-surface px-3 py-2 text-sm leading-relaxed text-content placeholder:text-content-subtle focus:border-brand focus:outline-none disabled:opacity-60"
        />
        <Button onClick={onSubmit} disabled={!value.trim() || busy} loading={busy}>
          Send
        </Button>
      </div>
      <p className="text-2xs text-content-subtle">
        <kbd className="font-mono">Enter</kbd> or{" "}
        <kbd className="font-mono">Ctrl</kbd>+
        <kbd className="font-mono">Enter</kbd> to send,{" "}
        <kbd className="font-mono">Shift</kbd>+
        <kbd className="font-mono">Enter</kbd> for a new line.
      </p>
    </div>
  );
}
