import { useEffect, useState } from "react";
import { Undo2 } from "lucide-react";

import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { ConfirmPhraseDialog } from "../ui/dialog";
import { EmptyState, ErrorState, SkeletonRows } from "../ui/feedback";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "../ui/table";
import { TierBadge } from "./TierBadge";
import { formatRelativeTime, humanize } from "../../lib/utils";
import api, { type AuditEntry } from "../../services/api";
import { useSentinelStore } from "../../store/sentinelStore";

/**
 * Everything the Sentinel actually did, and the button that takes it back.
 *
 * Undo works because every Tier 2 action captures the prior state and writes it
 * to the audit row *before* the change is applied. An action with no undo
 * payload — a Tier 3 one, or one that failed before capture — says so rather
 * than offering a button that would fail.
 *
 * Reversing is itself a change to a live workspace, so it is confirmed by
 * typing the resource name. It is a smaller decision than the original action
 * and still not one to make by mis-clicking.
 */
export function ActionsTakenPanel({ runId }: { runId: string }) {
  const undo = useSentinelStore((s) => s.undo);
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<AuditEntry | null>(null);
  const [undoing, setUndoing] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.sentinel.audit({ run_id: runId, limit: 200 });
      setEntries(result.entries);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const reverse = async (entry: AuditEntry) => {
    setUndoing(entry.id);
    const ok = await undo(entry.id);
    setUndoing(null);
    setConfirming(null);
    if (ok) void load();
  };

  if (error) {
    return <ErrorState message={error} onRetry={() => void load()} className="m-4" />;
  }

  if (loading && !entries.length) {
    return <SkeletonRows rows={4} columns={5} />;
  }

  if (!entries.length) {
    return (
      <EmptyState
        title="No actions were taken"
        description="This run recorded findings without changing anything. That is what audit mode does."
      />
    );
  }

  return (
    <>
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Resource</TableHeaderCell>
            <TableHeaderCell>Action</TableHeaderCell>
            <TableHeaderCell>Outcome</TableHeaderCell>
            <TableHeaderCell>When</TableHeaderCell>
            <TableHeaderCell className="text-right">Reverse</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {entries.map((entry) => (
            <TableRow key={entry.id}>
              <TableCell>
                <div className="font-mono text-2xs text-content">
                  {entry.resource_id}
                </div>
                <div className="text-2xs text-content-subtle">
                  {humanize(entry.resource_type)} · {entry.workspace}
                </div>
              </TableCell>

              <TableCell>
                <div className="flex items-center gap-1.5">
                  <TierBadge tier={entry.tier} />
                  <span className="font-mono text-2xs">{entry.effective_action}</span>
                </div>
                {entry.downgrade_reason && (
                  <div className="mt-0.5 text-2xs text-content-subtle">
                    requested {entry.requested_action} — {entry.downgrade_reason}
                  </div>
                )}
              </TableCell>

              <TableCell>
                {entry.outcome === "succeeded" ? (
                  <Badge variant="success">succeeded</Badge>
                ) : entry.outcome === "failed" ? (
                  <Badge variant="danger">failed</Badge>
                ) : (
                  <Badge variant="neutral">{entry.outcome}</Badge>
                )}
                {entry.error && (
                  <div className="mt-0.5 text-2xs text-danger">{entry.error}</div>
                )}
              </TableCell>

              <TableCell className="text-2xs text-content-muted">
                {formatRelativeTime(entry.started_at)}
              </TableCell>

              <TableCell className="text-right">
                {entry.undone_at ? (
                  <span className="text-2xs text-content-subtle">
                    reversed {formatRelativeTime(entry.undone_at)}
                  </span>
                ) : entry.undoable ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setConfirming(entry)}
                    loading={undoing === entry.id}
                  >
                    <Undo2 />
                    Undo
                  </Button>
                ) : (
                  <span
                    className="text-2xs text-content-subtle"
                    title="No undo payload was captured, so there is nothing to restore."
                  >
                    not reversible
                  </span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <ConfirmPhraseDialog
        open={Boolean(confirming)}
        onClose={() => setConfirming(null)}
        onConfirm={() => confirming && void reverse(confirming)}
        title="Reverse this action"
        phrase={confirming?.resource_id ?? ""}
        confirmLabel="Reverse it"
        loading={undoing != null}
      >
        <p>
          This restores the state captured before{" "}
          <span className="font-mono">{confirming?.effective_action}</span> was
          applied to <span className="font-mono">{confirming?.resource_id}</span>{" "}
          in {confirming?.workspace}.
        </p>
      </ConfirmPhraseDialog>
    </>
  );
}
