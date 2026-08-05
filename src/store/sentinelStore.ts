import { create } from "zustand";
import api, {
  ApiError,
  type Facets,
  type Finding,
  type FindingFilters,
  type Preflight,
  type ScanMode,
  type SentinelRun,
} from "../services/api";
import { toast } from "./toastStore";

/**
 * Dashboard state.
 *
 * Runs and findings are paginated on the server and held here separately,
 * because they are fetched independently: selecting a run must not refetch the
 * run list, and changing a finding filter must not refetch the run.
 *
 * Every fetch carries a sequence number. Filter changes arrive faster than
 * responses come back, and without it a slow response for a filter you have
 * already moved on from lands last and wins, so the table shows results that
 * do not match the controls above it.
 */

interface RunsState {
  runs: SentinelRun[];
  runsTotal: number;
  runsOffset: number;
  runsLimit: number;
  runsSearch: string;
  runsStatus: string;
  runsLoading: boolean;
  runsError: string | null;
}

interface FindingsState {
  selectedRunId: string | null;
  selectedRun: SentinelRun | null;
  runLoading: boolean;

  findings: Finding[];
  findingsTotal: number;
  findingsLoading: boolean;
  findingsError: string | null;
  filters: FindingFilters;
  facets: Facets | null;
}

interface Actions {
  loadRuns: () => Promise<void>;
  setRunsPage: (offset: number) => void;
  setRunsLimit: (limit: number) => void;
  setRunsSearch: (search: string) => void;
  setRunsStatus: (status: string) => void;

  selectRun: (runId: string | null) => Promise<void>;
  loadFindings: () => Promise<void>;
  setFilter: <K extends keyof FindingFilters>(key: K, value: FindingFilters[K]) => void;
  resetFilters: () => void;
  setFindingsPage: (skip: number) => void;

  triggerRun: (mode: ScanMode, workspaces?: string[], approvalId?: string) => Promise<void>;
  preflight: (runId: string) => Promise<Preflight | null>;
  undo: (auditId: number, undoneBy?: string) => Promise<boolean>;
}

type SentinelState = RunsState & FindingsState & Actions;

const DEFAULT_FILTERS: FindingFilters = {
  kind: "violation",
  skip: 0,
  limit: 50,
};

let runsSequence = 0;
let findingsSequence = 0;

const describe = (e: unknown) =>
  e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);

export const useSentinelStore = create<SentinelState>((set, get) => ({
  runs: [],
  runsTotal: 0,
  runsOffset: 0,
  runsLimit: 25,
  runsSearch: "",
  runsStatus: "",
  runsLoading: false,
  runsError: null,

  selectedRunId: null,
  selectedRun: null,
  runLoading: false,

  findings: [],
  findingsTotal: 0,
  findingsLoading: false,
  findingsError: null,
  filters: { ...DEFAULT_FILTERS },
  facets: null,

  loadRuns: async () => {
    const sequence = ++runsSequence;
    const { runsOffset, runsLimit, runsSearch, runsStatus } = get();
    set({ runsLoading: true, runsError: null });

    try {
      const page = await api.sentinel.runs({
        skip: runsOffset,
        limit: runsLimit,
        search: runsSearch || undefined,
        status: runsStatus || undefined,
        summary: true,
      });
      if (sequence !== runsSequence) return;
      set({ runs: page.runs, runsTotal: page.total, runsLoading: false });
    } catch (e) {
      if (sequence !== runsSequence) return;
      set({ runsError: describe(e), runsLoading: false });
    }
  },

  setRunsPage: (offset) => {
    set({ runsOffset: offset });
    void get().loadRuns();
  },

  setRunsLimit: (limit) => {
    set({ runsLimit: limit, runsOffset: 0 });
    void get().loadRuns();
  },

  setRunsSearch: (search) => {
    set({ runsSearch: search, runsOffset: 0 });
    void get().loadRuns();
  },

  setRunsStatus: (status) => {
    set({ runsStatus: status, runsOffset: 0 });
    void get().loadRuns();
  },

  selectRun: async (runId) => {
    if (!runId) {
      set({
        selectedRunId: null,
        selectedRun: null,
        findings: [],
        findingsTotal: 0,
        facets: null,
      });
      return;
    }

    set({
      selectedRunId: runId,
      runLoading: true,
      // Filters are per-run: carrying a `resource_type=cluster` filter into a
      // run that scanned no clusters shows an empty table and looks like a
      // failed scan.
      filters: { ...DEFAULT_FILTERS },
      findings: [],
      findingsTotal: 0,
      facets: null,
    });

    try {
      const run = await api.sentinel.run(runId);
      if (get().selectedRunId !== runId) return;
      set({ selectedRun: run, runLoading: false });
      // Facets come from loadFindings, so they are always counted over the
      // same filters as the table they sit above.
      await get().loadFindings();
    } catch (e) {
      if (get().selectedRunId !== runId) return;
      set({ runLoading: false, findingsError: describe(e) });
    }
  },

  loadFindings: async () => {
    const { selectedRunId, filters } = get();
    if (!selectedRunId) return;

    const sequence = ++findingsSequence;
    set({ findingsLoading: true, findingsError: null });

    try {
      // Paging must not reach the counts: page 4 of a filter still has the
      // same number of matches as page 1.
      const { skip: _skip, limit: _limit, ...facetFilters } = filters;

      const [page, facets] = await Promise.all([
        api.sentinel.findings(selectedRunId, filters),
        // A failed count is not worth failing the table for; the previous
        // numbers stay until the next successful load.
        api.sentinel.facets(selectedRunId, facetFilters).catch(() => get().facets),
      ]);
      if (sequence !== findingsSequence) return;
      set({
        findings: page.findings,
        findingsTotal: page.total,
        facets,
        findingsLoading: false,
      });
    } catch (e) {
      if (sequence !== findingsSequence) return;
      set({ findingsError: describe(e), findingsLoading: false });
    }
  },

  setFilter: (key, value) => {
    set((state) => ({
      // Any filter change returns to the first page. Staying on page 4 of a
      // narrower result set usually lands past the end.
      filters: { ...state.filters, [key]: value, skip: 0 },
    }));
    void get().loadFindings();
  },

  resetFilters: () => {
    set({ filters: { ...DEFAULT_FILTERS } });
    void get().loadFindings();
  },

  setFindingsPage: (skip) => {
    set((state) => ({ filters: { ...state.filters, skip } }));
    void get().loadFindings();
  },

  triggerRun: async (mode, workspaces, approvalId) => {
    try {
      const result = await api.sentinel.trigger({
        mode,
        workspaces,
        approval_id: approvalId,
      });
      const scanned = result.workspaces ?? [];
      toast.success(
        `Scan started in ${mode} mode`,
        scanned.length
          ? `${scanned.length} workspace${scanned.length === 1 ? "" : "s"}: ${scanned.join(", ")}`
          : "No workspaces matched.",
      );
      set({ runsOffset: 0 });
      await get().loadRuns();
    } catch (e) {
      toast.error("Could not start the scan", describe(e));
    }
  },

  preflight: async (runId) => {
    try {
      return await api.sentinel.preflight(runId);
    } catch (e) {
      toast.error("Preflight failed", describe(e));
      return null;
    }
  },

  undo: async (auditId, undoneBy) => {
    try {
      const result = await api.sentinel.undo(auditId, undoneBy);
      toast.success("Action reversed", `${result.action} on ${result.resource_id}`);
      await get().loadFindings();
      return true;
    } catch (e) {
      toast.error("Could not reverse the action", describe(e));
      return false;
    }
  },
}));
