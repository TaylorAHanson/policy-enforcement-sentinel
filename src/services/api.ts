/**
 * The single place the frontend talks to the backend.
 *
 * Every call goes through `request()`, which means one implementation of error
 * handling, JSON parsing, and query-string building rather than a slightly
 * different one at each of the forty-odd call sites. Before this, a failed
 * request surfaced as `undefined` propagating into a component and rendering
 * as a blank panel with no indication anything had gone wrong.
 *
 * Types here mirror the backend's serialisers. They are hand-written rather
 * than generated, so when a serialiser changes, this file changes with it.
 */

const BASE = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly detail?: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type QueryValue = string | number | boolean | null | undefined;

function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    // Omitting empty values keeps "no filter" out of the URL entirely, rather
    // than sending `severity=` and asking the backend to treat it as absent.
    if (value === null || value === undefined || value === "") continue;
    search.append(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

async function request<T>(
  path: string,
  options: RequestInit & { params?: Record<string, QueryValue> } = {},
): Promise<T> {
  const { params, ...init } = options;
  const response = await fetch(`${BASE}${path}${buildQuery(params)}`, {
    headers:
      init.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json", ...init.headers }
        : init.headers,
    ...init,
  });

  if (!response.ok) {
    // FastAPI puts the useful message in `detail`, which may be a string or a
    // list of validation errors. Both are worth showing; the status code alone
    // tells an operator nothing about which field they got wrong.
    let detail: unknown;
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body?.detail ?? body;
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail) && detail.length) {
        message = detail
          .map((e: { loc?: string[]; msg?: string }) =>
            e.msg ? `${e.loc?.slice(1).join(".") ?? ""} ${e.msg}`.trim() : String(e),
          )
          .join("; ");
      }
    } catch {
      /* Body was not JSON; the status line is all we have. */
    }
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const get = <T>(path: string, params?: Record<string, QueryValue>) =>
  request<T>(path, { method: "GET", params });

const post = <T>(path: string, body?: unknown, params?: Record<string, QueryValue>) =>
  request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
    params,
  });

const put = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "PUT",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

const del = <T>(path: string, params?: Record<string, QueryValue>) =>
  request<T>(path, { method: "DELETE", params });

// --- Types ------------------------------------------------------------------

export type ScanMode = "audit" | "remediate" | "enforce";

/** Mirrors ActionTier in app/core/actions.py. */
export const ActionTier = {
  Observe: 0,
  Notify: 1,
  Restrict: 2,
  Destructive: 3,
} as const;

export type ActionTier = (typeof ActionTier)[keyof typeof ActionTier];

export const TIER_LABELS: Record<number, string> = {
  0: "Observe",
  1: "Notify",
  2: "Restrict",
  3: "Destructive",
};

export interface ActionSpec {
  action: string;
  tier: number;
  tier_label: string;
  reversible: boolean;
  destructive: boolean;
  description: string;
  handler_method: string | null;
  undo_method: string | null;
}

export interface SentinelRun {
  id: string;
  workspace: string;
  environment: string;
  mode: ScanMode;
  status: "running" | "completed" | "failed" | string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  total_resources: number;
  violation_count: number;
  check_count: number;
  remediated_count: number;
  downgraded_count: number;
  approved_by: string | null;
  results?: Record<string, unknown> | null;
}

export interface Finding {
  id: number;
  run_id: string;
  kind: "violation" | "check" | string;
  workspace: string;
  environment: string | null;
  resource_id: string;
  resource_type: string;
  resource_name: string | null;
  owner: string | null;
  policy: string | null;
  rule_id: string | null;
  policy_id: string | null;
  category: string | null;
  severity: string | null;
  message: string;
  requested_action: string | null;
  effective_action: string | null;
  tier: number | null;
  requested_tier: number | null;
  downgraded: boolean;
  downgrade_reason: string | null;
  executed: boolean;
  data: Record<string, unknown> | null;
  created_at: string | null;
}

/** The envelope every server-paginated list shares. */
export interface Paginated {
  total: number;
  skip: number;
  limit: number;
}

export interface RunsPage extends Paginated {
  runs: SentinelRun[];
}

export interface FindingsPage extends Paginated {
  findings: Finding[];
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface Facets {
  severity: FacetValue[];
  category: FacetValue[];
  resource_type: FacetValue[];
  policy: FacetValue[];
  policy_id: FacetValue[];
  effective_action: FacetValue[];
}

/**
 * The index signature is what lets these go straight to `buildQuery`, which
 * drops empty values. Listing the keys explicitly as well keeps a typo in a
 * filter name a compile error rather than a silently ignored parameter.
 */
export interface FindingFilters extends Record<string, QueryValue> {
  kind?: string;
  severity?: string;
  category?: string;
  resource_type?: string;
  effective_action?: string;
  downgraded_only?: boolean;
  search?: string;
  skip?: number;
  limit?: number;
}

export interface PreflightTier {
  tier: number;
  count: number;
  resources: Array<{
    resource_id: string;
    resource_type: string;
    resource_name: string | null;
    owner: string | null;
    policy: string | null;
    policy_id: string | null;
    requested_action: string;
    workspace: string;
  }>;
  truncated: boolean;
}

export interface Preflight {
  run_id: string;
  workspaces: string[];
  by_tier: PreflightTier[];
  destructive_count: number;
  blast_radius_limit: number;
  exceeds_blast_radius: boolean;
  enforcement_enabled: boolean;
  allowed_workspaces: string[];
  action_ladder: ActionSpec[];
}

export interface AuditEntry {
  id: number;
  run_id: string | null;
  workspace: string;
  resource_id: string;
  resource_type: string;
  policy: string | null;
  requested_action: string;
  effective_action: string;
  tier: number;
  downgrade_reason: string | null;
  outcome: string;
  error: string | null;
  undoable: boolean;
  undone_at: string | null;
  started_at: string | null;
}

export interface PolicyRule {
  rule: string;
  id: string;
  category: string;
  severity: string;
  description: string;
  requested_action: string;
  tier: number;
  tier_label: string;
  destructive: boolean;
  escalate_after_days: number;
}

export interface PolicyMetadata {
  name: string;
  package: string;
  file: string;
  title: string;
  description: string;
  owner: string;
  domain: string;
  resource_type: string;
  authors: string[];
  rules: PolicyRule[];
  rule_count: number;
  max_tier: number;
  uncommitted_changes?: boolean;
  /** Names this policy was previously known by, from a rename. */
  replaces?: string[];
}

/** A policy's most recent commit, from git. */
export interface PolicyEdit {
  sha: string;
  short_sha: string;
  author: string;
  author_email: string;
  date: string;
  subject: string;
}

export interface PolicyDashboardRow extends PolicyMetadata {
  /** Null when the deployment has no git checkout to read history from. */
  last_edit: PolicyEdit | null;
  uncommitted_changes: boolean;
}

export interface PolicyDashboard {
  policies: PolicyDashboardRow[];
  summary: PolicyRegistry["summary"];
  /** Violation counts from the most recent scan, keyed by Rego package name. */
  findings_by_policy: Record<string, number>;
  latest_run: { run_id: string; started_at: string | null; status: string } | null;
  history_available: boolean;
  github_enabled: boolean;
  /** Resource types a handler actually discovers. */
  discovered_resource_types: string[];
}

export interface PolicyRegistry {
  policies: PolicyMetadata[];
  summary: {
    policy_count: number;
    rule_count: number;
    by_category: Record<string, number>;
    by_severity: Record<string, number>;
    by_tier: Record<string, number>;
    destructive_rule_count: number;
    max_tier: number;
  };
  action_ladder: ActionSpec[];
  renamed_policies: Array<{ legacy_name: string; replaced_by: string[] }>;
  history_available: boolean;
}

export interface PolicyRevision {
  sha: string;
  short_sha: string;
  author: string;
  author_email: string;
  date: string;
  subject: string;
}

/**
 * The state of the local policy working copy.
 *
 * `ok` means it was rebuilt from the target branch. `local` means the backend
 * is running against a git checkout and manages it with git instead.
 * `disabled` means GitHub is unconfigured, so the policies are whatever the
 * deployment shipped with.
 */
export interface PolicySyncStatus {
  status: "ok" | "failed" | "local" | "disabled" | "never";
  detail: string;
  at: string | null;
  commit: string | null;
  written: string[];
  removed: string[];
  configured: boolean;
  local_checkout: boolean;
  repo: string | null;
  branch: string;
  interval_seconds: number;
}

/**
 * `resource` waives every failing rule for one named resource.
 * `pattern` waives one rule for one resource type in one workspace.
 */
export type AllowlistMatchType = "resource" | "pattern";

export interface AllowlistEntry {
  /** A UUID generated by the application, not a sequence. */
  id: string;
  /** Null on pattern rows, which describe a class rather than a resource. */
  resource_id: string | null;
  resource_type: string;
  workspace: string;
  justification: string;
  status: string;
  match_type: AllowlistMatchType;
  /** The public rule ID a pattern waives, e.g. CST-CLU-005. Null otherwise. */
  rule_id: string | null;
  created_by: string | null;
  expires_at?: string | null;
  created_at?: string | null;
}

/** How much each exception is currently hiding, from the most recent scan. */
export interface AllowlistImpact {
  id: string;
  suppressed_findings: number;
  suppressed_resources: number;
  run_id: string;
}

export interface ResourceTypeOption {
  value: string;
  label: string;
}

// --- Testing Center --------------------------------------------------------

export interface SyntheticFixture {
  name: string;
  description: string;
  resource_type: string;
  workspace: string;
  environment: string;
  /** "captured" for fixtures taken from a real scan, "authored" otherwise. */
  source: string;
  expects_fires: string[];
  expects_passes: string[];
}

/** One rule's outcome for one fixture. */
export interface SyntheticRule {
  rule_id: string;
  violated: boolean;
  message: string | null;
  severity: string | null;
  /** What the policy asked for. Null when the rule passed. */
  requested_action: string | null;
  /** What would actually happen at the current settings. Null when it passed. */
  effective_action: string | null;
  downgraded: boolean;
  downgrade_reason: string | null;
  waived: boolean;
}

export interface SyntheticResult {
  fixture: string;
  description: string;
  resource_type: string;
  passed: boolean;
  /** Expected to fire and did not. The dangerous direction. */
  missing: string[];
  /** Fired without being expected to. */
  unexpected: string[];
  /** Expected to pass but fired. */
  wrongly_fired: string[];
  /** Named in the fixture but no policy evaluated it — usually a typo. */
  not_evaluated: string[];
  rules: SyntheticRule[];
  error?: string | null;
}

export interface SyntheticRun {
  passed: number;
  failed: number;
  total: number;
  ok: boolean;
  enforcement_enabled: boolean;
  /** True when unsaved editor content was tested instead of the committed file. */
  tested_draft: boolean;
  results: SyntheticResult[];
}

/** How much of a policy any fixture actually exercises. */
export interface RuleCoverage {
  rule_id: string;
  title: string;
  policy: string;
  resource_type: string;
  fires_in: string[];
  passes_in: string[];
  covered: boolean;
  /** Whether any fixture shows the rule leaving a compliant resource alone. */
  has_negative_case: boolean;
  /**
   * The rule has been seen firing on a resource discovery could really return.
   *
   * Fixtures build the input document directly, so one can hand a policy a
   * field no handler collects. The rule then passes its test and stays dead in
   * the estate, which is worse than no test at all, because the green tick gets
   * read as evidence.
   */
  reachable: boolean;
  /** Why this rule is or is not shown working. See `RuleCategory`. */
  category: RuleCategory;
  /** Fields the rule reads that no handler collects. */
  missing_fields: string[];
  /**
   * For each missing field that cannot simply be collected, why not. Empty
   * when the field is merely uncollected, where the category says it all.
   */
  blockers: RuleBlocker[];
}

/** Why a field the rule needs cannot just be added to a handler. */
export interface RuleBlocker {
  field: string;
  /**
   * The access that would make this readable, e.g. "metastore admin". Empty
   * when no access exists to ask for, because Databricks publishes nothing.
   */
  requirement: string;
  detail: string;
}

/**
 * Why a rule has never been shown working — and so, who can fix it.
 *
 * "No test" is not one problem. A rule waiting on data the scanner does not
 * collect, a rule for a type nothing scans, and a rule that reads real data and
 * still never matches need three different people to do three different things.
 */
export type RuleCategory =
  | "working"
  /** Reads collected data, and something about it cannot match. Likely a bug. */
  | "suspect"
  /** Reads collected data, nothing obviously wrong, nobody wrote a test. */
  | "untested"
  /** Reads a collectable field no handler collects. The work is in the handler. */
  | "needs_discovery"
  /**
   * Reads a field the platform will not show to the identity the scanner runs
   * as. More collector code will not help; somebody has to grant something.
   */
  | "needs_permission"
  /** Reads a field Databricks does not publish at any permission level. */
  | "not_exposed"
  /** Governs a resource type nothing discovers at all. */
  | "no_handler";

export interface CategoryInfo {
  label: string;
  detail: string;
  action: string;
  owner: string;
}

/** One field, and the rules that are waiting on discovery to collect it. */
export interface BlockedField {
  field: string;
  rules: string[];
  rule_count: number;
  resource_types: string[];
}

export interface CoverageReport {
  rules: RuleCoverage[];
  total: number;
  covered: number;
  uncovered: number;
  /** Covered by a fixture that only uses data the scanner really produces. */
  reachable: number;
  /** Covered, but only by a fixture inventing data. Looks tested, is dead. */
  only_synthetic: number;
  fixture_count: number;
  fixtures_inventing_fields: string[];
  by_category: Record<RuleCategory, number>;
  categories: Record<RuleCategory, CategoryInfo>;
  /** Ordered by how many rules each field would unblock. */
  blocked_on: BlockedField[];
  /** Permission-blocked rules folded into the grants that would release them. */
  asks: AccessAsk[];
  /** Resource types a rule governs and no handler discovers. */
  unscanned_types: string[];
}

/**
 * One thing to ask an administrator for, and what it turns on.
 *
 * Ten blocked rules are not ten problems. Grouped by the grant they wait on
 * they are three requests, and a request is something a person can act on —
 * "one grant starts six rules" is a decision, "ten rules are blocked" is a
 * status.
 */
export interface AccessAsk {
  /** What has to be granted, e.g. "SELECT on the system catalog". */
  requirement: string;
  detail: string;
  rules: string[];
  rule_count: number;
  fields: string[];
  resource_types: string[];
}

/**
 * A disagreement between the field catalogue and a real estate.
 *
 * Everything else here is checked *against* `discovered_fields`. This is the
 * only check of `discovered_fields` itself, so it is the only one that can
 * catch a rule the coverage report is calling healthy.
 */
export interface DriftFinding {
  kind: "never_emitted" | "undeclared" | "impossible_comparison" | "inert";
  resource_type: string;
  field: string;
  resource_count: number;
  detail: string;
  /** Present on impossible_comparison only. */
  policy?: string;
  compared_against?: string[];
  observed_values?: string[];
}

export interface DriftResourceType {
  resource_type: string;
  resource_count: number;
  scanned: boolean;
  /** False when too few resources were seen to conclude anything. */
  conclusive: boolean;
  never_emitted: string[];
  undeclared: string[];
  impossible_comparisons: DriftFinding[];
  inert: string[];
  unregistered?: boolean;
}

export interface DriftReport {
  /** False until a scan has recorded what the handlers emit. */
  available: boolean;
  reason?: string;
  run_id?: string;
  observed_at?: string | null;
  resource_types: DriftResourceType[];
  /** The catalogue and the estate disagree; one of them is wrong. */
  findings: DriftFinding[];
  /** They agree, and no rule reading these fields can fire today. */
  inert: DriftFinding[];
  counts: Record<string, number>;
  total: number;
}

/**
 * A field a policy reads that discovery never collects.
 *
 * Not a compile error — that is the problem. The rule is valid Rego that can
 * never match, so it reports every resource as compliant, forever.
 */
export interface FieldWarning {
  field: string;
  resource_type: string;
  message: string;
}

export interface ResourceField {
  name: string;
  description: string;
  common?: boolean;
}

export interface ResourceTypeSchema {
  resource_type: string;
  handler: string;
  declared: boolean;
  fields: ResourceField[];
}

export interface CaptureResult {
  captured: {
    name: string;
    resource_type: string;
    fires: string[];
    passes: string[];
  }[];
  count: number;
  directory: string;
  note: string;
}

export interface PytestCase {
  name: string;
  classname: string;
  file: string | null;
  line: string | null;
  time: number;
  outcome: "passed" | "failed" | "error" | "skipped";
  detail: string | null;
}

export interface PytestRun {
  suite: string;
  keyword: string | null;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  duration_seconds: number;
  exit_code: number;
  ok: boolean;
  output: string;
  tests: PytestCase[];
  /** Set when the run produced no usable report, e.g. nothing was collected. */
  error?: string;
}

export type SettingType =
  | "bool"
  | "int"
  | "string"
  | "select"
  | "color"
  | "cron"
  | "secret";

export interface CronPreview {
  expression: string;
  valid: boolean;
  error: string | null;
  /** Blank is a legitimate value: it turns scheduled scanning off. */
  disabled: boolean;
  next_runs: string[];
}

export interface SettingDefinition {
  key: string;
  group: string;
  label: string;
  help: string;
  type: SettingType;
  value: unknown;
  overridden: boolean;
  danger: boolean;
  options?: string[];
  placeholder?: string;
  /** Secrets only. Their `value` is always null; these say what is in place. */
  configured?: boolean;
  hint?: string | null;
}

export interface SettingGroup {
  name: string;
  danger: boolean;
  fields: SettingDefinition[];
}

export interface SettingsSchema {
  groups: SettingGroup[];
  enforcement_enabled: boolean;
  destructive_workspaces: string[];
  gates: Array<{ gate: string; description: string }>;
  action_ladder: ActionSpec[];
}

export interface Branding {
  name?: string;
  logo_url?: string;
  primary_color?: string;
}

export interface Release {
  version: string;
  date: string;
  title: string;
  /** The one line worth reading if you read nothing else. */
  highlight: string;
  body: string;
}

// --- The policy assistant ---------------------------------------------------

export interface AgentStatus {
  enabled: boolean;
  configured: boolean;
  model: string;
  via_gateway: boolean;
  reasoning_effort: string;
  max_iterations: number;
  tools: string[];
  /** The highest tier the assistant is permitted to generate. Enforced server-side. */
  max_generated_tier: number;
  tracing_enabled: boolean;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AgentToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  error?: string | null;
}

export interface AgentAnswer {
  answer: string;
  /** True when the loop hit its iteration or time limit. The answer is partial. */
  truncated: boolean;
  tool_calls: AgentToolCall[];
}

export interface AuthoredPolicy {
  content: string;
  policy_name: string;
  package: string;
  is_new_file: boolean;
  valid: boolean;
  validation_errors: string[];
  attempts: number;
  max_tier: number;
  requested_actions: string[];
}

/** A 422 from `/agent/author`: the model asked for more than Tier 2. */
export interface GuardrailViolation {
  error: "guardrail_violation";
  violations: string[];
  remedy: string;
}

export interface AgentChatReply {
  answer: string;
  /** Present only when the reply ended with a complete policy file. */
  proposal: AuthoredPolicy | null;
  /**
   * The tier guardrail withdrawing a proposal. Unlike `/agent/author`, this
   * arrives as a 200 alongside the prose rather than a 422, because the
   * assistant's explanation of what it was attempting is worth keeping.
   */
  refusal: GuardrailViolation | null;
  /**
   * Fields the proposal reads that no handler collects.
   *
   * Not a refusal. The policy is safe and compiles; it simply cannot ever
   * match, which is a thing to tell the reviewer rather than block on.
   */
  field_warnings: FieldWarning[];
  truncated: boolean;
  tool_calls: AgentToolCall[];
}

export interface PrNotes {
  body: string;
  /** Rendered first, and separately, because a reviewer must not scroll past one. */
  escalations: string[];
  action_changes: string[];
  new_rules: string[];
  blast_radius: {
    run_id: number | null;
    total_findings: number;
    by_rule: Record<string, number>;
    affected_owners: number;
    available: boolean;
  };
  max_tier: number;
}

// --- Endpoints --------------------------------------------------------------

export const api = {
  branding: {
    get: () => get<Branding>("/branding"),
  },

  sentinel: {
    runs: (params?: {
      skip?: number;
      limit?: number;
      search?: string;
      status?: string;
      summary?: boolean;
    }) => get<RunsPage>("/sentinel/runs", params),

    run: (runId: string) => get<SentinelRun>(`/sentinel/runs/${runId}`),

    findings: (runId: string, filters?: FindingFilters) =>
      get<FindingsPage>(`/sentinel/runs/${runId}/findings`, filters),

    facets: (runId: string, filters?: FindingFilters) =>
      get<Facets>(`/sentinel/runs/${runId}/facets`, filters),

    /**
     * Starts one run across every selected workspace. A single `run_id` covers
     * all of them — they are one run, which is what makes the dashboard totals
     * add up — so this is deliberately not a list of ids.
     */
    trigger: (body: { mode: ScanMode; workspaces?: string[]; approval_id?: string }) =>
      post<{
        message: string;
        run_id: string;
        mode: string;
        workspaces: string[];
      }>("/sentinel/run", body),

    purge: (olderThanDays: number) =>
      del<{ purged: number; older_than_days: number }>("/sentinel/runs", {
        older_than_days: olderThanDays,
      }),

    preflight: (runId: string, mode: ScanMode = "enforce") =>
      post<Preflight>("/sentinel/enforcement/preflight", { run_id: runId, mode }),

    approve: (body: {
      workspace: string;
      approved_by: string;
      confirm_workspace: string;
    }) =>
      post<{ approval_id: string; workspace: string; expires_in_minutes: number }>(
        "/sentinel/enforcement/approve",
        body,
      ),

    executeAction: (
      runId: string,
      body: {
        resource_id: string;
        resource_type: string;
        action: string;
        policy_name?: string;
        reason?: string;
        workspace?: string;
      },
    ) =>
      post<{
        success: boolean;
        requested_action: string;
        effective_action: string;
        tier: number;
        downgraded: boolean;
        downgrade_reason: string | null;
      }>(`/sentinel/runs/${runId}/enforcement-action`, body),

    audit: (params?: {
      run_id?: string;
      undoable_only?: boolean;
      skip?: number;
      limit?: number;
    }) => get<{ total: number; entries: AuditEntry[] }>("/sentinel/audit", params),

    undo: (auditId: number, undoneBy?: string) =>
      post<{
        undone: boolean;
        audit_id: number;
        action: string;
        resource_id: string;
      }>(`/sentinel/actions/${auditId}/undo`, { undone_by: undoneBy }),
  },

  policies: {
    list: () => get<string[]>("/policies/"),
    get: (name: string) => get<{ name: string; content: string }>(`/policies/${name}`),
    /**
     * Proposes retiring a policy. There is no direct delete: the file lives in
     * git, so removing it is a reviewed pull request like any other change.
     */
    remove: (name: string) =>
      del<{ message: string; pr_url: string; branch: string }>(
        `/policies/${name}`,
      ),
    validate: (policy_name: string, content: string) =>
      post<{
        valid: boolean;
        errors: string[];
        skipped?: boolean;
        /** Compiles fine but can never fire. Separate from errors on purpose. */
        warnings?: FieldWarning[];
      }>("/policies/validate", { policy_name, content }),

    /** Every field a policy may read, per resource type. */
    schema: () =>
      get<{
        resource_types: ResourceTypeSchema[];
        input_document: Record<string, Record<string, string>>;
      }>("/policies/schema"),
    evaluate: (body: {
      policy_name: string;
      content: string;
      query: string;
      input_data: Record<string, unknown>;
    }) =>
      post<{ success: boolean; result?: unknown; error?: string }>(
        "/policies/evaluate",
        body,
      ),
    createPr: (name: string, content: string) =>
      post<{
        message: string;
        pr_url: string;
        branch: string;
        escalations: string[];
        explanation_committed: boolean;
      }>(`/policies/${name}/pr`, { content }),
    config: () => get<{ github_enabled: boolean; target_branch: string }>(
      "/policies/config",
    ),

    /** Everything the policy list needs, in one request. */
    dashboard: () => get<PolicyDashboard>("/policies/dashboard"),

    /**
     * Propose renaming a policy.
     *
     * Not a file move: the package declaration is rewritten and the old name
     * recorded, so exceptions naming the old spelling keep resolving.
     */
    rename: (name: string, new_name: string) =>
      post<{
        message: string;
        pr_url: string;
        branch: string;
        old_name: string;
        new_name: string;
        new_package: string;
      }>(`/policies/${name}/rename`, { new_name }),

    /** Starting text for a new policy. Writes nothing. */
    scaffold: (body: {
      name: string;
      resource_type: string;
      owner?: string;
      domain?: string;
      title?: string;
      description?: string;
    }) => post<{ name: string; content: string }>("/policies/scaffold", body),

    scaffoldDefaults: () =>
      get<{
        resource_types: {
          resource_type: string;
          suggested_name: string;
          already_governed: boolean;
        }[];
      }>("/policies/scaffold/defaults"),

    /** How current the local working copy is against the target branch. */
    syncStatus: () => get<PolicySyncStatus>("/policies/sync"),
    sync: () => post<PolicySyncStatus>("/policies/sync", {}),

    registry: () => get<PolicyRegistry>("/policies/metadata"),
    metadata: (name: string) => get<PolicyMetadata>(`/policies/${name}/metadata`),
    history: (name: string, limit = 50) =>
      get<{
        available: boolean;
        reason?: string;
        revisions: PolicyRevision[];
        uncommitted_changes?: boolean;
      }>(`/policies/${name}/history`, { limit }),
    restore: (name: string) =>
      post<{ name: string; content: string; uncommitted_changes: boolean }>(
        `/policies/${name}/restore`,
        {},
      ),
    revision: (name: string, sha: string, diff = false) =>
      get<{ name: string; sha: string; diff: boolean; content: string }>(
        `/policies/${name}/history/${sha}`,
        { diff },
      ),
  },

  allowlist: {
    list: () => get<AllowlistEntry[]>("/allowlist/"),
    /** Served rather than hardcoded, because the hardcoded list had drifted. */
    resourceTypes: () => get<ResourceTypeOption[]>("/allowlist/resource-types"),
    impact: () => get<AllowlistImpact[]>("/allowlist/impact"),
    create: (body: {
      resource_type: string;
      workspace: string;
      justification: string;
      match_type?: AllowlistMatchType;
      /** Required for `resource`, refused for `pattern`. */
      resource_id?: string | null;
      /** Required for `pattern`, refused for `resource`. */
      rule_id?: string | null;
      created_by?: string | null;
      status?: string;
      /** Required for `pattern`: a class-wide waiver has to end. */
      expires_at?: string | null;
    }) => post<AllowlistEntry>("/allowlist/", body),
    remove: (id: string) => del<{ message: string }>(`/allowlist/${id}`),
  },

  settings: {
    schema: () => get<SettingsSchema>("/settings"),
    cronPreview: (expression: string) =>
      get<CronPreview>("/settings/cron-preview", { expression }),
    update: (key: string, value: unknown, updatedBy?: string) =>
      put<{ key: string; value: unknown }>(`/settings/${key}`, {
        value,
        updated_by: updatedBy,
      }),
    updateMany: (values: Record<string, unknown>, updatedBy?: string) =>
      put<{ applied: Record<string, unknown>; errors: Record<string, string> }>(
        "/settings",
        { values, updated_by: updatedBy },
      ),
    reset: (key: string) => del<{ key: string; value: unknown }>(`/settings/${key}`),
  },

  readme: {
    get: () => get<{ content: string }>("/readme"),
  },

  agent: {
    status: () => get<AgentStatus>("/agent/status"),

    ask: (body: { question: string; history?: ChatTurn[] }) =>
      post<AgentAnswer>("/agent/ask", body),

    /** Answers, and proposes an edit when one was asked for. Nothing is written. */
    chat: (body: {
      message: string;
      history?: ChatTurn[];
      target_policy?: string;
      open_content?: string;
    }) => post<AgentChatReply>("/agent/chat", body),

    /** Returns a proposal. Saving it is a separate, human-initiated call. */
    author: (body: {
      instruction: string;
      target_policy?: string;
      existing_content?: string;
    }) => post<AuthoredPolicy>("/agent/author", body),

    /** Generates an explanation. Storing it means committing it in a PR. */
    explain: (body: { policy_name: string; content: string }) =>
      post<{ policy_name: string; explanation: string }>("/agent/explain", body),

    /** The committed sibling `.md`. Offline and cheap; try this first. */
    committedExplanation: (policyName: string) =>
      get<{
        policy_name: string;
        explanation: string | null;
        exists: boolean;
      }>(`/agent/explain/${encodeURIComponent(policyName)}`),

    prNotes: (body: {
      policy_name: string;
      new_content: string;
      old_content?: string;
    }) => post<PrNotes>("/agent/pr-notes", body),
  },

  testing: {
    /** What is available to run, without running it. */
    fixtures: () =>
      get<{ fixtures: SyntheticFixture[]; directory: string }>(
        "/testing/fixtures",
      ),

    /**
     * Fixtures through the real policies. Never touches a workspace.
     *
     * Pass `draft_policy` and `draft_content` together to test unsaved editor
     * content instead of the committed file — which is what the editor does,
     * since testing the committed version of a policy you are midway through
     * changing answers a question nobody asked.
     */
    synthetic: (body?: {
      fixtures?: string[];
      resource_type?: string;
      draft_policy?: string;
      draft_content?: string;
    }) => post<SyntheticRun>("/testing/synthetic", body ?? {}),

    /** Which rules any fixture exercises, and which nothing covers. */
    coverage: (params?: { resource_type?: string; policy?: string }) =>
      get<CoverageReport>("/testing/coverage", params),

    /**
     * Where the field catalogue disagrees with the last real scan.
     *
     * Needs a scan to have happened. Against fixtures it would only confirm
     * that fixtures match the catalogue, which is true by construction.
     */
    drift: () => get<DriftReport>("/testing/drift"),

    /** Writes fixtures from the resources a real scan already recorded. */
    capture: (body?: {
      run_id?: string;
      resource_ids?: string[];
      limit?: number;
      anonymise?: boolean;
    }) => post<CaptureResult>("/testing/capture", body ?? {}),

    suites: () =>
      get<{ suites: { name: string; path: string; available: boolean }[] }>(
        "/testing/suites",
      ),

    /** Runs the Python suite in a subprocess. Slow — around 30s for all of it. */
    pytest: (body?: { suite?: string; keyword?: string }) =>
      post<PytestRun>("/testing/pytest", body ?? {}),
  },

  releaseNotes: {
    list: () =>
      get<{
        releases: Release[];
        latest_version: string | null;
        latest_highlight: string;
      }>("/release-notes"),

    /** Version and headline only, for the sidebar badge. Null on a fresh repo. */
    latest: () =>
      get<Omit<Release, "body" | "version"> & { version: string | null }>(
        "/release-notes/latest",
      ),
  },
};

export default api;
