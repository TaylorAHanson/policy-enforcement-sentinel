import { GitBranch, RefreshCw } from "lucide-react";
import { Alert } from "../ui/feedback";
import { Button } from "../ui/button";
import type { PolicySyncStatus } from "../../services/api";

const relative = (iso: string | null): string => {
  if (!iso) return "never";
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
};

/**
 * How current the evaluated policies are.
 *
 * The directory OPA reads is a copy of the target branch, so "when was this
 * last pulled" is the difference between a merged pull request being in force
 * and it being invisible. Worth a line of UI, because the failure it prevents —
 * a reviewer merging a fix and watching the scan keep flagging — is otherwise
 * indistinguishable from the policy not working.
 */
export function PolicySyncBanner({
  sync,
  onRefresh,
}: {
  sync: PolicySyncStatus | null;
  onRefresh: () => void;
}) {
  // A local checkout is the developer's own working copy: git is already the
  // store and there is nothing to reconcile.
  if (!sync || sync.status === "local" || sync.status === "disabled") return null;

  const refresh = (
    <Button variant="ghost" size="sm" onClick={onRefresh}>
      <RefreshCw className="size-3" />
      Refresh
    </Button>
  );

  if (sync.status === "failed") {
    return (
      <Alert
        tone="danger"
        title="The policy working copy is out of date"
        action={refresh}
      >
        The last sync from {sync.repo}@{sync.branch} failed, so scans are running
        against the previous copy. {sync.detail}
      </Alert>
    );
  }

  return (
    <p className="flex items-center gap-2 text-2xs text-content-subtle">
      <GitBranch className="size-3.5" />
      Evaluating {sync.repo}@{sync.branch}, synced {relative(sync.at)}.
      <button
        type="button"
        onClick={onRefresh}
        className="underline underline-offset-2 hover:text-content"
      >
        Refresh
      </button>
    </p>
  );
}
