import { useState } from "react";
import { GitCommitHorizontal, RotateCcw } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Dialog } from "../ui/dialog";
import { Alert, EmptyState, Spinner } from "../ui/feedback";
import { formatRelativeTime, formatTimestamp } from "../../lib/utils";
import type { PolicyRevision } from "../../services/api";

/**
 * Commit history for the selected policy, read from the git checkout.
 *
 * Policies are code, so their history already exists. Storing a second copy in
 * the database would duplicate state and go stale the first time somebody edits
 * a policy through a pull request instead of this editor.
 */
export function PolicyHistoryPanel({
  revisions,
  available,
  uncommitted,
  policyName,
  onView,
  onRestore,
}: {
  revisions: PolicyRevision[];
  available: boolean;
  uncommitted?: boolean;
  policyName?: string;
  onView: (sha: string) => Promise<string | null>;
  onRestore?: () => Promise<void>;
}) {
  const [loadingSha, setLoadingSha] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ sha: string; content: string } | null>(null);
  const [confirmingRestore, setConfirmingRestore] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const restore = async () => {
    if (!onRestore) return;
    setRestoring(true);
    await onRestore();
    setRestoring(false);
  };

  if (!available) {
    return (
      <EmptyState
        title="History is not available here"
        description="This deployment does not have the policies in a git checkout, so there is no commit history to read. Policy history is available when running from a clone of the repository."
      />
    );
  }

  const view = async (sha: string) => {
    setLoadingSha(sha);
    const content = await onView(sha);
    if (content != null) setPreview({ sha, content });
    setLoadingSha(null);
  };

  return (
    <div className="space-y-3 p-4">
      {uncommitted && (
        <Alert tone="warning" title="Uncommitted changes in the working copy">
          <p>
            This file differs from the last commit below, and the working copy is
            what a scan evaluates — so the estate is being judged against a rule
            nobody has reviewed. Open a pull request to keep the change, or
            discard it and go back to the committed version.
          </p>
          {onRestore && (
            <div className="mt-2 flex items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setConfirmingRestore(true)}
                disabled={restoring}
                loading={restoring}
              >
                <RotateCcw />
                Discard local changes
              </Button>
              {confirmingRestore && (
                <span className="text-2xs text-content-muted">
                  This cannot be undone.
                </span>
              )}
            </div>
          )}
        </Alert>
      )}

      {/* A plain confirmation rather than the type-the-phrase one: what is
          being discarded was never reviewed or recorded, so a mistaken click
          costs one local edit, not a change to what runs against the estate. */}
      <Dialog
        open={confirmingRestore}
        onClose={() => setConfirmingRestore(false)}
        title="Discard local changes?"
        description={`${policyName ?? "This policy"} will be restored to the last commit. An edit made to it outside the app cannot be recovered afterwards.`}
        tone="danger"
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmingRestore(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setConfirmingRestore(false);
                void restore();
              }}
            >
              Discard
            </Button>
          </>
        }
      />

      {revisions.length === 0 ? (
        <EmptyState
          title="No commits yet"
          description="This policy has not been committed. Its history starts once it lands on a branch."
        />
      ) : (
        <ol className="space-y-2">
          {revisions.map((revision) => (
            <li
              key={revision.sha}
              className="rounded-md border border-border bg-surface-raised px-3 py-2.5"
            >
              <div className="flex items-start gap-2">
                <GitCommitHorizontal
                  className="mt-0.5 size-3.5 shrink-0 text-content-subtle"
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs text-content">{revision.subject}</p>
                  <p className="mt-0.5 text-2xs text-content-subtle">
                    {revision.author} ·{" "}
                    <span title={formatTimestamp(revision.date)}>
                      {formatRelativeTime(revision.date)}
                    </span>
                  </p>
                </div>
                <Badge variant="outline" className="shrink-0 font-mono">
                  {revision.short_sha}
                </Badge>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void view(revision.sha)}
                  loading={loadingSha === revision.sha}
                >
                  View
                </Button>
              </div>

              {preview?.sha === revision.sha && (
                <pre className="mt-2 max-h-80 overflow-auto rounded border border-border bg-canvas px-3 py-2 text-2xs leading-relaxed text-content-muted">
                  {preview.content}
                </pre>
              )}
            </li>
          ))}
        </ol>
      )}

      {loadingSha && (
        <div className="flex items-center gap-2 text-2xs text-content-subtle">
          <Spinner className="size-3" />
          Loading revision…
        </div>
      )}
    </div>
  );
}
