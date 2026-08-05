import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { Badge } from "../ui/badge";
import { EmptyState, ErrorState, SkeletonRows } from "../ui/feedback";
import { Pagination } from "../ui/pagination";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "../ui/table";
import { cn, formatNumber, formatRelativeTime, formatTimestamp } from "../../lib/utils";
import type { SentinelRun } from "../../services/api";

const STATUS = {
  running: { Icon: Loader2, cls: "text-info animate-spin", label: "Running" },
  completed: { Icon: CheckCircle2, cls: "text-success", label: "Completed" },
  failed: { Icon: XCircle, cls: "text-danger", label: "Failed" },
} as const;

function StatusCell({ run }: { run: SentinelRun }) {
  const status = STATUS[run.status as keyof typeof STATUS] ?? {
    Icon: AlertTriangle,
    cls: "text-content-subtle",
    label: run.status,
  };
  return (
    <div className="flex items-center gap-1.5">
      <status.Icon className={cn("size-3.5 shrink-0", status.cls)} aria-hidden />
      <span className="text-xs">{status.label}</span>
    </div>
  );
}

const MODE_VARIANT = {
  audit: "neutral",
  remediate: "warning",
  enforce: "danger",
} as const;

export function RunsTable({
  runs,
  total,
  offset,
  limit,
  loading,
  error,
  selectedRunId,
  onSelect,
  onOffsetChange,
  onLimitChange,
  onRetry,
}: {
  runs: SentinelRun[];
  total: number;
  offset: number;
  limit: number;
  loading: boolean;
  error: string | null;
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
  onOffsetChange: (offset: number) => void;
  onLimitChange: (limit: number) => void;
  onRetry: () => void;
}) {
  if (error) {
    return <ErrorState message={error} onRetry={onRetry} className="m-4" />;
  }

  // Only show skeletons on the first load. Repainting them on every poll makes
  // a stable table flicker once every few seconds.
  if (loading && !runs.length) {
    return <SkeletonRows rows={6} columns={6} />;
  }

  if (!runs.length) {
    return (
      <EmptyState
        title="No scans yet"
        description="Run a scan to evaluate your workspaces against the current policies. Audit mode records findings without touching anything."
      />
    );
  }

  return (
    <>
      <Table>
        <TableHead>
          <tr>
            <TableHeaderCell>Workspace</TableHeaderCell>
            <TableHeaderCell>Mode</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell className="text-right">Resources</TableHeaderCell>
            <TableHeaderCell className="text-right">Violations</TableHeaderCell>
            <TableHeaderCell className="text-right">Acted</TableHeaderCell>
            <TableHeaderCell>Started</TableHeaderCell>
          </tr>
        </TableHead>
        <TableBody>
          {runs.map((run) => (
            <TableRow
              key={run.id}
              interactive
              selected={run.id === selectedRunId}
              onClick={() => onSelect(run.id)}
            >
              <TableCell className="max-w-[220px]">
                <div className="truncate font-medium text-content">{run.workspace}</div>
                <div className="truncate text-2xs text-content-subtle">
                  {run.environment}
                </div>
              </TableCell>
              <TableCell>
                <Badge variant={MODE_VARIANT[run.mode] ?? "neutral"}>{run.mode}</Badge>
              </TableCell>
              <TableCell>
                <StatusCell run={run} />
                {run.error && (
                  <div
                    className="mt-0.5 max-w-[240px] truncate text-2xs text-danger"
                    title={run.error}
                  >
                    {run.error}
                  </div>
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatNumber(run.total_resources)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                <span className={run.violation_count ? "text-warning" : undefined}>
                  {formatNumber(run.violation_count)}
                </span>
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {run.remediated_count ? (
                  <span className="text-content">{formatNumber(run.remediated_count)}</span>
                ) : (
                  <span className="text-content-subtle">—</span>
                )}
                {run.downgraded_count > 0 && (
                  <div
                    className="text-2xs text-content-subtle"
                    title={`${run.downgraded_count} action(s) were downgraded by a safety gate`}
                  >
                    {formatNumber(run.downgraded_count)} downgraded
                  </div>
                )}
              </TableCell>
              <TableCell title={formatTimestamp(run.started_at)}>
                {formatRelativeTime(run.started_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Pagination
        offset={offset}
        limit={limit}
        total={total}
        onOffsetChange={onOffsetChange}
        onLimitChange={onLimitChange}
        busy={loading}
      />
    </>
  );
}
