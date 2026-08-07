import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  FileStack,
  Play,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardHeader, CardTitle, StatCard } from "../components/ui/card";
import { Select } from "../components/ui/input";
import { Alert, Spinner } from "../components/ui/feedback";
import { Tabs } from "../components/ui/tabs";
import { ActionsTakenPanel } from "../components/safety/ActionsTakenPanel";
import { EnforcePreflightDialog } from "../components/safety/EnforcePreflightDialog";
import { TierLegend } from "../components/safety/TierBadge";
import { FacetFilters } from "../components/sentinel/FacetFilters";
import { FindingDetail } from "../components/sentinel/FindingDetail";
import { FindingsTable } from "../components/sentinel/FindingsTable";
import { RunsTable } from "../components/sentinel/RunsTable";
import { formatNumber, formatRelativeTime } from "../lib/utils";
import api, { type Finding, type FindingChanges, type ScanMode } from "../services/api";
import { WhatChanged } from "../components/sentinel/WhatChanged";
import { useSentinelStore } from "../store/sentinelStore";
import { useSettingsStore } from "../store/settingsStore";

/** How often to refresh while a scan is in flight. */
const POLL_INTERVAL_MS = 5000;

export default function SentinelDashboard() {
  const store = useSentinelStore();
  const enforcementEnabled = useSettingsStore((s) => s.enforcementEnabled());

  const [mode, setMode] = useState<ScanMode>("audit");
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null);
  const [preflightOpen, setPreflightOpen] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [detailTab, setDetailTab] = useState<"findings" | "actions">("findings");
  const [changes, setChanges] = useState<FindingChanges | null>(null);

  useEffect(() => {
    void store.loadRuns();
    // Only on mount: loadRuns reads its own filters from the store, so adding
    // it as a dependency would refetch on every keystroke in the search box.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** The run the panel describes: the selection, or the newest completed scan
   *  when nothing is selected.
   *
   *  Derived rather than read from `selectedRunId` directly, because that stays
   *  null until somebody clicks a row. Keyed off it alone, the panel loaded once
   *  and then sat there — a scan would finish, the run table and the cards would
   *  update around it, and it would still be describing the scan before. */
  const describedRunId = useMemo(() => {
    if (store.selectedRunId) return store.selectedRunId;
    const completed = store.runs
      .filter((r) => r.status === "completed")
      .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""));
    return completed[0]?.id ?? null;
  }, [store.selectedRunId, store.runs]);

  useEffect(() => {
    // Follows the described run. Pinned to the newest scan it sat above cards
    // describing a different one, so the panel could say 3,789 open while the
    // Violations card said 3,041 — both correct, and nothing on screen saying
    // they were answering about different scans.
    //
    // Best effort: if the delta cannot be computed the dashboard still works,
    // and an error banner about a summary is worse than its absence.
    let current = true;
    api.sentinel
      .changes(describedRunId ?? undefined)
      .then((data) => current && setChanges(data))
      .catch(() => current && setChanges(null));
    return () => {
      current = false;
    };
  }, [describedRunId]);

  const hasRunningScan = useMemo(
    () => store.runs.some((run) => run.status === "running"),
    [store.runs],
  );

  useEffect(() => {
    // Poll only while something is actually running. The old dashboard polled
    // every five seconds forever, which meant a dashboard left open overnight
    // made seventeen thousand requests to watch nothing change.
    if (!hasRunningScan) return;
    const timer = setInterval(() => {
      void store.loadRuns();
      if (store.selectedRunId) void store.loadFindings();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasRunningScan, store.selectedRunId]);

  const run = store.selectedRun;

  const startScan = async (scanMode: ScanMode, approvalId?: string, workspace?: string) => {
    setTriggering(true);
    await store.triggerRun(scanMode, workspace ? [workspace] : undefined, approvalId);
    setTriggering(false);
  };

  const onRunClick = () => {
    // Enforce never starts from the toolbar. It goes through preflight, which
    // is where the blast radius and the gates are shown.
    if (mode === "enforce") {
      if (!store.selectedRunId) return;
      setPreflightOpen(true);
      return;
    }
    void startScan(mode);
  };

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-content">Governance Sentinel</h1>
          <p className="mt-1 text-xs text-content-muted">
            Scans evaluate every workspace against the current policies. Audit mode
            records findings and changes nothing.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Select
            value={mode}
            onChange={(e) => setMode(e.target.value as ScanMode)}
            aria-label="Scan mode"
            className="w-[190px]"
          >
            <option value="audit">Audit — record only</option>
            <option value="remediate">Remediate — reversible actions</option>
            <option value="enforce" disabled={!enforcementEnabled}>
              Enforce — destructive{enforcementEnabled ? "" : " (disabled)"}
            </option>
          </Select>

          <Button
            variant={mode === "enforce" ? "danger" : "primary"}
            onClick={onRunClick}
            loading={triggering}
            disabled={mode === "enforce" && !store.selectedRunId}
            title={
              mode === "enforce" && !store.selectedRunId
                ? "Select a completed audit run first — enforcement is previewed against real findings"
                : undefined
            }
          >
            {mode === "enforce" ? <ShieldAlert /> : <Play />}
            {mode === "enforce" ? "Review and enforce" : "Run scan"}
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={() => void store.loadRuns()}
            aria-label="Refresh"
          >
            <RefreshCw className={store.runsLoading ? "animate-spin" : undefined} />
          </Button>
        </div>
      </header>

      {mode === "enforce" && (
        <Alert tone="enforcement" title="Enforce mode selected">
          Nothing runs until you review the preflight and type the workspace name.
          Destructive actions additionally require all five gates to agree.
        </Alert>
      )}

      {/* Above the totals on purpose. The totals answer "what is wrong", which
          is four digits and has not moved in weeks; this answers "what changed",
          which is usually a handful and is the only part anybody can act on. */}
      {changes && <WhatChanged changes={changes} />}

      {run && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatCard
            label="Resources"
            value={formatNumber(run.total_resources)}
            hint={run.workspace}
            icon={<FileStack className="size-4" />}
          />
          <StatCard
            label="Violations"
            value={formatNumber(run.violation_count)}
            tone={run.violation_count ? "warning" : "success"}
            icon={<AlertTriangle className="size-4" />}
          />
          <StatCard
            label="Passing checks"
            value={formatNumber(run.check_count)}
            tone="success"
            icon={<ShieldCheck className="size-4" />}
          />
          <StatCard
            label="Actions taken"
            value={formatNumber(run.remediated_count)}
            hint={run.mode === "audit" ? "audit mode takes none" : undefined}
          />
          <StatCard
            label="Downgraded"
            value={formatNumber(run.downgraded_count)}
            tone={run.downgraded_count ? "info" : "default"}
            hint={run.downgraded_count ? "a gate refused a stronger action" : undefined}
            icon={<ArrowDownRight className="size-4" />}
          />
        </div>
      )}

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Scan history</CardTitle>
          {hasRunningScan && (
            <span className="flex items-center gap-1.5 text-2xs text-info">
              <Spinner className="size-3" />
              a scan is running
            </span>
          )}
        </CardHeader>
        <RunsTable
          runs={store.runs}
          total={store.runsTotal}
          offset={store.runsOffset}
          limit={store.runsLimit}
          loading={store.runsLoading}
          error={store.runsError}
          selectedRunId={store.selectedRunId}
          onSelect={(id) => void store.selectRun(id)}
          onOffsetChange={store.setRunsPage}
          onLimitChange={store.setRunsLimit}
          onRetry={() => void store.loadRuns()}
        />
      </Card>

      {store.selectedRunId && (
        <Card>
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>
                Findings
                {run && (
                  <span className="ml-2 font-normal text-content-subtle">
                    {run.workspace} · {formatRelativeTime(run.started_at)}
                  </span>
                )}
              </CardTitle>
              <TierLegend className="mt-2" />
            </div>
            <div className="flex items-center gap-2">
              {run?.approved_by && (
                <Badge variant="danger" size="md">
                  enforced, approved by {run.approved_by}
                </Badge>
              )}
              <Button variant="ghost" size="sm" onClick={() => void store.selectRun(null)}>
                Close
              </Button>
            </div>
          </CardHeader>

          <Tabs
            value={detailTab}
            onChange={(id) => setDetailTab(id as typeof detailTab)}
            items={[
              { id: "findings", label: "Findings", count: store.findingsTotal },
              {
                id: "actions",
                label: "Actions taken",
                count: run?.remediated_count ?? 0,
              },
            ]}
          />

          {detailTab === "findings" ? (
            <>
              <FacetFilters
                facets={store.facets}
                filters={store.filters}
                onChange={store.setFilter}
                onReset={store.resetFilters}
                disabled={store.runLoading}
              />

              <FindingsTable
                findings={store.findings}
                total={store.findingsTotal}
                filters={store.filters}
                loading={store.findingsLoading}
                error={store.findingsError}
                selectedId={selectedFinding?.id ?? null}
                onSelect={setSelectedFinding}
                onPageChange={store.setFindingsPage}
                onLimitChange={(limit) => store.setFilter("limit", limit)}
                onRetry={() => void store.loadFindings()}
              />
            </>
          ) : (
            <ActionsTakenPanel runId={store.selectedRunId} />
          )}
        </Card>
      )}

      <FindingDetail finding={selectedFinding} onClose={() => setSelectedFinding(null)} />

      <EnforcePreflightDialog
        open={preflightOpen}
        runId={store.selectedRunId}
        onClose={() => setPreflightOpen(false)}
        onApproved={(approvalId, workspace, scanMode) =>
          void startScan(scanMode, approvalId, workspace)
        }
      />
    </div>
  );
}
