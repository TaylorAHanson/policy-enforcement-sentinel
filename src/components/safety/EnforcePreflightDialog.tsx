import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Dialog } from "../ui/dialog";
import { Alert, Spinner } from "../ui/feedback";
import { Field, Input } from "../ui/input";
import { Select } from "../ui/input";
import { TierBadge, TierLegend } from "./TierBadge";
import { formatNumber, humanize, truncateMiddle } from "../../lib/utils";
import api, { type Preflight, type ScanMode } from "../../services/api";
import { toast } from "../../store/toastStore";

/**
 * The last thing between an operator and an irreversible change.
 *
 * It answers, against real data from a completed audit run, what enforcement
 * would actually do: how many resources at each tier, in which workspaces, and
 * which of the five gates currently disagree. Only then does it offer to mint
 * an approval, and only after the workspace name has been typed out.
 *
 * The approval it produces is scoped to one workspace and expires. It is not a
 * setting, and it does not survive a restart.
 */
export function EnforcePreflightDialog({
  open,
  runId,
  onClose,
  onApproved,
}: {
  open: boolean;
  runId: string | null;
  onClose: () => void;
  onApproved: (approvalId: string, workspace: string, mode: ScanMode) => void;
}) {
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [loading, setLoading] = useState(false);
  const [workspace, setWorkspace] = useState("");
  const [approvedBy, setApprovedBy] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open || !runId) return;

    setLoading(true);
    setPreflight(null);
    setConfirmText("");

    api.sentinel
      .preflight(runId)
      .then((result) => {
        setPreflight(result);
        // Preselect only when there is no ambiguity. Choosing one of several
        // workspaces on the operator's behalf is how the wrong one gets
        // approved.
        setWorkspace(result.workspaces.length === 1 ? result.workspaces[0] : "");
      })
      .catch((e: Error) => toast.error("Preflight failed", e.message))
      .finally(() => setLoading(false));
  }, [open, runId]);

  const destructive = preflight?.destructive_count ?? 0;
  const workspaceAllowed =
    Boolean(workspace) && (preflight?.allowed_workspaces ?? []).includes(workspace);
  const canApprove =
    Boolean(workspace) &&
    Boolean(approvedBy.trim()) &&
    confirmText.trim() === workspace &&
    workspaceAllowed &&
    !preflight?.exceeds_blast_radius;

  const approve = async () => {
    if (!workspace) return;
    setSubmitting(true);
    try {
      const result = await api.sentinel.approve({
        workspace,
        approved_by: approvedBy.trim(),
        confirm_workspace: confirmText.trim(),
      });
      toast.warning(
        "Enforcement approved",
        `${workspace} · expires in ${result.expires_in_minutes} minutes`,
      );
      onApproved(result.approval_id, workspace, "enforce");
      onClose();
    } catch (e) {
      toast.error("Approval refused", e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      tone="danger"
      dismissible={!submitting}
      title={
        <span className="flex items-center gap-2">
          <ShieldAlert className="size-4" aria-hidden />
          Enforce this run
        </span>
      }
      description="Review exactly what would change before approving. This preview is built from this run's real findings."
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={approve}
            disabled={!canApprove}
            loading={submitting}
          >
            Approve and run enforcement
          </Button>
        </>
      }
    >
      {loading ? (
        <div className="flex items-center justify-center gap-2 py-10 text-content-muted">
          <Spinner />
          <span className="text-xs">Working out the blast radius…</span>
        </div>
      ) : !preflight ? (
        <p className="py-6 text-center text-xs text-content-muted">
          No preflight data available for this run.
        </p>
      ) : (
        <div className="space-y-4">
          <TierLegend className="rounded-md border border-border bg-surface-raised px-3 py-2" />

          <div className="space-y-2">
            {preflight.by_tier.length === 0 ? (
              <Alert tone="success" title="Nothing to enforce">
                This run produced no findings that request an action.
              </Alert>
            ) : (
              preflight.by_tier.map((group) => (
                <div
                  key={group.tier}
                  className="rounded-md border border-border bg-surface-raised"
                >
                  <div className="flex items-center gap-2 border-b border-border px-3 py-2">
                    <TierBadge tier={group.tier} />
                    <span className="text-xs text-content">
                      {formatNumber(group.count)} resource
                      {group.count === 1 ? "" : "s"}
                    </span>
                  </div>
                  <ul className="max-h-36 divide-y divide-border overflow-auto">
                    {group.resources.slice(0, 25).map((r) => (
                      <li
                        key={`${r.workspace}:${r.resource_id}`}
                        className="flex items-center justify-between gap-3 px-3 py-1.5 text-2xs"
                      >
                        <span className="min-w-0 flex-1 truncate text-content">
                          {r.resource_name || truncateMiddle(r.resource_id, 40)}
                          <span className="text-content-subtle">
                            {" "}
                            · {humanize(r.resource_type)}
                          </span>
                        </span>
                        <code className="shrink-0 font-mono text-content-muted">
                          {r.requested_action}
                        </code>
                      </li>
                    ))}
                  </ul>
                  {(group.truncated || group.count > 25) && (
                    <p className="border-t border-border px-3 py-1.5 text-2xs text-content-subtle">
                      Showing 25 of {formatNumber(group.count)}.
                    </p>
                  )}
                </div>
              ))
            )}
          </div>

          {/* The gates, stated plainly. An operator who cannot enforce should be
              able to see which condition is missing without reading the logs. */}
          <div className="space-y-1.5 rounded-md border border-border bg-surface-raised px-3 py-2.5 text-2xs">
            <GateRow
              ok={preflight.enforcement_enabled}
              label="Enforcement is enabled in Settings"
            />
            <GateRow
              ok={preflight.allowed_workspaces.length > 0}
              label={`Workspaces cleared for destructive actions: ${preflight.allowed_workspaces.join(", ") || "none"}`}
            />
            <GateRow
              ok={!preflight.exceeds_blast_radius}
              label={`${formatNumber(destructive)} destructive candidate${destructive === 1 ? "" : "s"}, limit ${formatNumber(preflight.blast_radius_limit)}`}
            />
          </div>

          {preflight.exceeds_blast_radius && (
            <Alert tone="danger" title="Blast radius exceeded">
              This run would take {formatNumber(destructive)} irreversible actions,
              over the limit of {formatNumber(preflight.blast_radius_limit)}. The whole
              run is refused rather than partially applied. Narrow the policies or
              raise the limit deliberately in Settings.
            </Alert>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Workspace" required>
              <Select
                value={workspace}
                onChange={(e) => {
                  setWorkspace(e.target.value);
                  setConfirmText("");
                }}
              >
                <option value="">Choose a workspace…</option>
                {preflight.workspaces.map((ws) => (
                  <option key={ws} value={ws}>
                    {ws}
                  </option>
                ))}
              </Select>
            </Field>

            <Field label="Approved by" required description="Recorded on every action.">
              <Input
                value={approvedBy}
                onChange={(e) => setApprovedBy(e.target.value)}
                placeholder="you@company.com"
              />
            </Field>
          </div>

          {workspace && !workspaceAllowed && (
            <Alert tone="danger" title="Workspace not cleared">
              <code className="font-mono">{workspace}</code> is not in
              DESTRUCTIVE_ACTION_WORKSPACES. Add it in Settings first — deliberately a
              separate step from approving a run.
            </Alert>
          )}

          <Field
            label={
              <>
                Type <span className="font-mono text-danger">{workspace || "the workspace name"}</span> to confirm
              </>
            }
            required
          >
            <Input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              disabled={!workspace}
              autoComplete="off"
              spellCheck={false}
              className="font-mono"
            />
          </Field>
        </div>
      )}
    </Dialog>
  );
}

function GateRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <Badge variant={ok ? "success" : "danger"} size="sm">
        {ok ? "pass" : "blocked"}
      </Badge>
      <span className={ok ? "text-content-muted" : "text-danger"}>{label}</span>
    </div>
  );
}
