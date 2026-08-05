import { CheckCircle2, ShieldCheck } from "lucide-react";
import { SeverityBadge } from "../ui/badge";
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
import { ActionCell } from "../safety/TierBadge";
import { humanize, truncateMiddle } from "../../lib/utils";
import type { Finding, FindingFilters } from "../../services/api";

export function FindingsTable({
  findings,
  total,
  filters,
  loading,
  error,
  selectedId,
  onSelect,
  onPageChange,
  onLimitChange,
  onRetry,
}: {
  findings: Finding[];
  total: number;
  filters: FindingFilters;
  loading: boolean;
  error: string | null;
  selectedId: number | null;
  onSelect: (finding: Finding) => void;
  onPageChange: (skip: number) => void;
  onLimitChange: (limit: number) => void;
  onRetry: () => void;
}) {
  if (error) {
    return <ErrorState message={error} onRetry={onRetry} className="m-4" />;
  }

  if (loading && !findings.length) {
    return <SkeletonRows rows={8} columns={5} />;
  }

  if (!findings.length) {
    const filtered =
      Boolean(filters.search) ||
      Boolean(filters.severity) ||
      Boolean(filters.category) ||
      Boolean(filters.resource_type) ||
      Boolean(filters.effective_action) ||
      Boolean(filters.downgraded_only);

    return filtered ? (
      <EmptyState
        title="Nothing matches these filters"
        description="Widen or clear the filters to see the rest of this run's results."
      />
    ) : filters.kind === "violation" ? (
      <EmptyState
        icon={<ShieldCheck className="size-8" />}
        title="No violations"
        description="Every resource this run evaluated complied with the policies that applied to it."
      />
    ) : (
      <EmptyState
        title="No results"
        description="This run recorded no findings of that kind."
      />
    );
  }

  return (
    <>
      <Table>
        <TableHead>
          <tr>
            <TableHeaderCell>Resource</TableHeaderCell>
            <TableHeaderCell>Policy</TableHeaderCell>
            <TableHeaderCell>Severity</TableHeaderCell>
            <TableHeaderCell>Finding</TableHeaderCell>
            <TableHeaderCell>Action</TableHeaderCell>
          </tr>
        </TableHead>
        <TableBody>
          {findings.map((finding) => (
            <TableRow
              key={finding.id}
              interactive
              selected={finding.id === selectedId}
              onClick={() => onSelect(finding)}
            >
              <TableCell className="max-w-[240px]">
                <div className="truncate font-medium text-content">
                  {finding.resource_name || truncateMiddle(finding.resource_id, 34)}
                </div>
                <div className="truncate text-2xs text-content-subtle">
                  {humanize(finding.resource_type)}
                  {finding.owner ? ` · ${finding.owner}` : ""}
                </div>
              </TableCell>

              <TableCell className="max-w-[180px]">
                <div className="truncate text-xs text-content">
                  {finding.policy_id || finding.rule_id || finding.policy || "—"}
                </div>
                {finding.category && (
                  <div className="truncate text-2xs text-content-subtle">
                    {humanize(finding.category)}
                  </div>
                )}
              </TableCell>

              <TableCell>
                {finding.kind === "check" ? (
                  <span
                    className="inline-flex items-center gap-1 text-2xs text-success"
                    title="This rule was evaluated and the resource complied"
                  >
                    <CheckCircle2 className="size-3.5" aria-hidden />
                    Pass
                  </span>
                ) : (
                  <SeverityBadge severity={finding.severity} />
                )}
              </TableCell>

              <TableCell className="max-w-[420px]">
                <p className="line-clamp-2 text-xs leading-relaxed">
                  {finding.message || "—"}
                </p>
              </TableCell>

              <TableCell>
                <ActionCell
                  requestedAction={finding.requested_action}
                  effectiveAction={finding.effective_action}
                  tier={finding.tier}
                  requestedTier={finding.requested_tier}
                  downgradeReason={finding.downgrade_reason}
                  executed={finding.executed}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Pagination
        offset={filters.skip ?? 0}
        limit={filters.limit ?? 50}
        total={total}
        onOffsetChange={onPageChange}
        onLimitChange={onLimitChange}
        busy={loading}
      />
    </>
  );
}
