import { useMemo, useState } from "react";
import { DiffEditor, Editor } from "@monaco-editor/react";
import { GitCommitHorizontal, RotateCcw, X } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Combobox, type ComboboxOption } from "../ui/combobox";
import { Dialog } from "../ui/dialog";
import { Alert, EmptyState, Spinner } from "../ui/feedback";
import { formatRelativeTime, formatTimestamp } from "../../lib/utils";
import type { PolicyRevision } from "../../services/api";

const READ_ONLY = {
  readOnly: true,
  minimap: { enabled: false },
  fontSize: 12,
  scrollBeyondLastLine: false,
  automaticLayout: true,
};

const DIFF_OPTIONS = {
  ...READ_ONLY,
  // Inline rather than side by side: the panel is often half the window, and
  // two columns of Rego at that width wrap into nonsense.
  renderSideBySide: false,
  renderOverviewRuler: false,
};

type Mode = "diff" | "full";

/**
 * Commit history for the selected policy, read from the git checkout.
 *
 * Policies are code, so their history already exists. Storing a second copy in
 * the database would duplicate state and go stale the first time somebody edits
 * a policy through a pull request instead of this editor.
 *
 * The question people actually bring here is "what changed", not "what did the
 * file look like" — so a revision opens as a diff against what is in the editor
 * now, with the whole file one click away.
 */
export function PolicyHistoryPanel({
  revisions,
  available,
  uncommitted,
  policyName,
  currentContent,
  onView,
  onRestore,
}: {
  revisions: PolicyRevision[];
  available: boolean;
  uncommitted?: boolean;
  policyName?: string;
  currentContent: string;
  onView: (sha: string) => Promise<string | null>;
  onRestore?: () => Promise<void>;
}) {
  // The policy is part of the opened revision rather than a separate reset,
  // because a sha belongs to one file: carrying it across a policy switch
  // would diff one policy against another and look like an enormous change.
  // Tagging it makes a stale selection unrepresentable instead of something an
  // effect has to race to clear.
  const [opened, setOpened] = useState<{
    policy?: string;
    sha: string;
    content: string | null;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<Mode>("diff");
  const [confirmingRestore, setConfirmingRestore] = useState(false);
  const [restoring, setRestoring] = useState(false);

  const current = opened?.policy === policyName ? opened : null;
  const selected = current?.sha ?? null;
  const content = current?.content ?? null;

  const options = useMemo<ComboboxOption[]>(
    () =>
      revisions.map((revision) => ({
        value: revision.sha,
        label: revision.subject,
        description: `${revision.author} · ${formatRelativeTime(revision.date)}`,
        keywords: `${revision.short_sha} ${revision.author}`,
        badge: (
          <Badge variant="outline" className="font-mono">
            {revision.short_sha}
          </Badge>
        ),
      })),
    [revisions],
  );

  const open = async (sha: string) => {
    setOpened({ policy: policyName, sha, content: null });
    setLoading(true);
    const loaded = await onView(sha);
    setOpened({ policy: policyName, sha, content: loaded });
    setLoading(false);
  };

  const close = () => setOpened(null);

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

  const revision = revisions.find((r) => r.sha === selected) ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-3 p-4 pb-3">
        {uncommitted && (
          <Alert tone="warning" title="Uncommitted changes in the working copy">
            <p>
              This file differs from the last commit below, and the working copy
              is what a scan evaluates — so the estate is being judged against a
              rule nobody has reviewed. Open a pull request to keep the change,
              or discard it and go back to the committed version.
            </p>
            {onRestore && (
              <div className="mt-2">
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
              </div>
            )}
          </Alert>
        )}

        {revisions.length === 0 ? (
          <EmptyState
            title="No commits yet"
            description="This policy has not been committed. Its history starts once it lands on a branch."
          />
        ) : (
          <div className="flex items-center gap-2">
            <Combobox
              className="min-w-0 flex-1"
              options={options}
              value={selected}
              onChange={(sha) => void open(sha)}
              placeholder={`${revisions.length} commit${revisions.length === 1 ? "" : "s"} — pick one to compare`}
              searchPlaceholder="Search commits, authors, hashes"
              emptyMessage="No commit matches."
            />

            {selected && (
              <>
                <div className="flex shrink-0 overflow-hidden rounded-md border border-border-strong">
                  {(["diff", "full"] as Mode[]).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setMode(m)}
                      className={`px-2.5 py-1.5 text-2xs transition-colors ${
                        mode === m
                          ? "bg-accent-subtle text-accent"
                          : "text-content-muted hover:text-content"
                      }`}
                    >
                      {m === "diff" ? "Changes" : "Whole file"}
                    </button>
                  ))}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={close}
                  title="Close this revision"
                  aria-label="Close this revision"
                >
                  <X />
                </Button>
              </>
            )}
          </div>
        )}

        {revision && (
          <p className="flex flex-wrap items-center gap-x-2 text-2xs text-content-subtle">
            <GitCommitHorizontal className="size-3.5 shrink-0" aria-hidden />
            <span className="text-content">{revision.author}</span>
            <span title={formatTimestamp(revision.date)}>
              {formatRelativeTime(revision.date)}
            </span>
            {mode === "diff" && (
              <span>
                · comparing this commit against what is in the editor now
              </span>
            )}
          </p>
        )}
      </div>

      {/* Takes whatever height is left, rather than the fixed 320px this used
          to be. A policy is a few hundred lines and the answer is rarely in
          the first twenty. */}
      <div className="min-h-0 flex-1 border-t border-border">
        {loading ? (
          <div className="flex items-center gap-2 p-4 text-2xs text-content-subtle">
            <Spinner className="size-3" />
            Loading revision…
          </div>
        ) : !selected ? (
          <div className="flex h-full items-center justify-center p-6 text-center text-2xs text-content-subtle">
            {revisions.length > 0 &&
              "Choose a commit above to see what it changed."}
          </div>
        ) : content == null ? (
          <div className="p-4 text-2xs text-danger">
            That revision could not be read.
          </div>
        ) : mode === "diff" ? (
          <DiffEditor
            height="100%"
            language="rego"
            theme="vs-dark"
            original={content}
            modified={currentContent}
            options={DIFF_OPTIONS}
          />
        ) : (
          <Editor
            height="100%"
            language="rego"
            theme="vs-dark"
            value={content}
            options={READ_ONLY}
          />
        )}
      </div>

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
    </div>
  );
}
