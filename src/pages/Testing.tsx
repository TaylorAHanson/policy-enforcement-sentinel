import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Camera,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Filter,
  FlaskConical,
  Play,
  RefreshCw,
  TerminalSquare,
  XCircle,
} from "lucide-react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Input,
  Select,
  Spinner,
  Tabs,
} from "../components/ui";
import { RuleHealth } from "../components/policy/RuleHealth";
import { CatalogueDrift } from "../components/policy/CatalogueDrift";
import api, {
  type CaptureResult,
  type CoverageReport,
  type DriftReport,
  type PytestRun,
  type SyntheticFixture,
  type SyntheticResult,
  type SyntheticRun,
} from "../services/api";
import { cn } from "../lib/utils";

/**
 * Running the tests without leaving the app.
 *
 * Two things live here, and they answer different questions. A policy test asks
 * "does this rule fire on the thing I think it fires on", by putting one
 * resource through the real policies, the real action ladder, and real OPA. The
 * pytest run asks "is the application still correct". Neither touches a
 * workspace: the policy test runner has no client to touch one with.
 *
 * The word is "test" rather than "fixture" throughout the interface. A fixture
 * is the input half of a test and the name is accurate, but only to somebody
 * who already knows the harness — and the people who most need this page are
 * the ones who do not.
 *
 * The page is ordered by how fast things change, not by how much detail they
 * carry. A run result is about what you just did and is stale in a minute; rule
 * coverage moves once a week and is mostly not the reader's to act on. Showing
 * them at the same weight made a standing metric look like an error message.
 */

type Tab = "policy" | "pytest";

export default function Testing() {
  const [tab, setTab] = useState<Tab>("policy");

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col gap-4 p-6">
      <header>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-content">
          <FlaskConical className="size-5 text-accent" aria-hidden />
          Testing Center
        </h1>
        <p className="mt-1 text-[13px] text-content-muted">
          Check a policy against known resources, or run the application suite.
          Nothing here reaches a workspace or changes anything in one.
        </p>
      </header>

      <Tabs
        value={tab}
        onChange={(id) => setTab(id as Tab)}
        items={[
          { id: "policy", label: "Policy tests" },
          { id: "pytest", label: "Application tests" },
        ]}
      />

      {tab === "policy" ? <FixturePanel /> : <PytestPanel />}
    </div>
  );
}

/**
 * What the page is for, for somebody who has not used it.
 *
 * Sits above the buttons because the first question is "what does this do",
 * and the page previously opened with a red block of results to a question
 * nobody had asked yet.
 */
function WhatThisIs() {
  return (
    <div className="rounded-md border border-border bg-surface-raised/50 px-3 py-2 text-xs leading-relaxed text-content-muted">
      <span className="font-medium text-content">
        A policy test is one resource plus the rules that should and should not
        fire on it.
      </span>{" "}
      Run them after editing a policy, to confirm it still catches what you think
      it catches and has not started flagging things it should leave alone. Write
      them by hand for a case you have in mind, or capture them from a scan to
      pin down how the policies treat resources you really have.
    </div>
  );
}

// --- Fixtures ---------------------------------------------------------------

function FixturePanel() {
  const [fixtures, setFixtures] = useState<SyntheticFixture[]>([]);
  const [run, setRun] = useState<SyntheticRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [captured, setCaptured] = useState<CaptureResult | null>(null);
  const [coverage, setCoverage] = useState<CoverageReport | null>(null);
  const [drift, setDrift] = useState<DriftReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** After a failing run, the list is usually only worth reading for failures. */
  const [failuresOnly, setFailuresOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, cover, catalogue] = await Promise.all([
        api.testing.fixtures(),
        api.testing.coverage(),
        api.testing.drift(),
      ]);
      setFixtures(data.fixtures);
      setCoverage(cover);
      setDrift(catalogue);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runAll = async () => {
    setRunning(true);
    setError(null);
    try {
      setRun(await api.testing.synthetic());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const capture = async () => {
    setCapturing(true);
    setError(null);
    try {
      const result = await api.testing.capture({ limit: 25 });
      setCaptured(result);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCapturing(false);
    }
  };

  const resultsByFixture = useMemo(() => {
    const map = new Map<string, SyntheticResult>();
    run?.results.forEach((r) => map.set(r.fixture, r));
    return map;
  }, [run]);

  const failedNames = useMemo(
    () => (run?.results ?? []).filter((r) => !r.passed).map((r) => r.fixture),
    [run],
  );

  const shown = useMemo(
    () =>
      failuresOnly
        ? fixtures.filter((f) => failedNames.includes(f.name))
        : fixtures,
    [fixtures, failuresOnly, failedNames],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-8 text-[13px] text-content-muted">
        <Spinner /> Loading tests…
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <WhatThisIs />

      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={runAll} disabled={running || !fixtures.length}>
          {running ? <Spinner /> : <Play />}
          {running ? "Running…" : `Run ${fixtures.length} tests`}
        </Button>
        <Button variant="outline" onClick={capture} disabled={capturing}>
          {capturing ? <Spinner /> : <Camera />}
          Capture from a scan
        </Button>
        <Button variant="ghost" onClick={() => void load()}>
          <RefreshCw />
          Reload
        </Button>
      </div>

      {error && <ErrorState message={error} onRetry={() => void load()} />}

      {/* What just happened, first. This is the only thing on the page that
          changed because of something the reader did, and it was previously a
          badge in the corner while a standing metric took the whole width. */}
      {run && (
        <RunResult
          run={run}
          failedNames={failedNames}
          failuresOnly={failuresOnly}
          onToggleFailures={() => setFailuresOnly(!failuresOnly)}
        />
      )}

      {/* Then anything actionable that a run cannot tell you. Both of these are
          real problems with the tests themselves, so they stay expanded. */}
      {coverage && coverage.only_synthetic > 0 && (
        <Alert
          tone="danger"
          title={`${coverage.only_synthetic} rules are tested with data that does not exist`}
        >
          A test builds the input document directly, so it can hand a policy a
          field no handler collects. These rules pass and are still dead against
          a real workspace — worse than untested, because the green tick reads as
          evidence. The tests doing it are{" "}
          {coverage.fixtures_inventing_fields.join(", ")}.
        </Alert>
      )}

      {drift?.available && drift.total > 0 && <CatalogueDrift drift={drift} />}

      {/* Standing coverage, folded. It moves once a week and most of it is not
          the reader's to act on; only the rules that look broken are hoisted. */}
      {coverage && <CoverageFold coverage={coverage} />}

      <ContextStrip run={run} drift={drift} captured={captured} />

      {!fixtures.length ? (
        <EmptyState
          icon={<FlaskConical className="size-6" />}
          title="No policy tests yet"
          description="A policy test is one resource plus the rules that should and should not fire on it. Capture some from a scan, or add JSON files to backend/fixtures/synthetic/."
        />
      ) : (
        <div className="flex flex-col gap-2">
          {shown.map((fixture) => (
            <FixtureRow
              key={fixture.name}
              fixture={fixture}
              result={resultsByFixture.get(fixture.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** The outcome of the run the reader just asked for. */
function RunResult({
  run,
  failedNames,
  failuresOnly,
  onToggleFailures,
}: {
  run: SyntheticRun;
  failedNames: string[];
  failuresOnly: boolean;
  onToggleFailures: () => void;
}) {
  if (!run.failed) {
    return (
      <Alert tone="success" title={`All ${run.total} tests passed`}>
        Every rule these tests name fired where it should and stayed quiet where
        it should not.
      </Alert>
    );
  }

  return (
    <Alert
      tone="danger"
      title={`${run.failed} of ${run.total} tests failed`}
      action={
        <Button variant="outline" size="sm" onClick={onToggleFailures}>
          <Filter />
          {failuresOnly ? "Show all tests" : "Show only failures"}
        </Button>
      }
    >
      <div className="flex flex-wrap gap-1.5">
        {failedNames.map((name) => (
          <code key={name} className="font-mono text-2xs text-danger">
            {name}
          </code>
        ))}
      </div>
    </Alert>
  );
}

/**
 * How much the tests prove, out of the way until asked for.
 *
 * This was a full-width red block with a ✗ on it, which reads as "something
 * just broke". Nothing broke — the number has been the same for days, and most
 * of the gap needs an access grant or a handler rather than anything the reader
 * can do from this page. The one part that is a live problem, a rule that looks
 * broken, is hoisted out so it is visible without expanding.
 */
function CoverageFold({ coverage }: { coverage: CoverageReport }) {
  const [open, setOpen] = useState(false);
  const suspect = coverage.rules.filter((rule) => rule.category === "suspect");
  const blocked = coverage.total - coverage.reachable - suspect.length;
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="rounded-md border border-border">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface-hover"
      >
        <Chevron className="size-3.5 shrink-0 text-content-subtle" />
        <span className="text-xs font-medium text-content">
          {coverage.reachable} of {coverage.total} rules proven
        </span>
        {suspect.length > 0 && (
          <Badge variant="danger">
            {suspect.length} {suspect.length === 1 ? "looks" : "look"} broken
          </Badge>
        )}
        {blocked > 0 && (
          <span className="text-2xs text-content-muted">
            {blocked} blocked on access, a handler, or the platform
          </span>
        )}
      </button>

      {/* Always visible, collapsed or not. It is the only part of coverage that
          is both wrong and fixable from here. */}
      {!open && suspect.length > 0 && (
        <ul className="border-t border-border px-3 py-2">
          {suspect.map((rule) => (
            <li key={rule.rule_id} className="text-2xs text-content-muted">
              <code className="font-mono text-danger">{rule.rule_id}</code> —{" "}
              {rule.title}
            </li>
          ))}
        </ul>
      )}

      {open && (
        <div className="border-t border-border p-3">
          {/* Headless: the button above already says 45 of 64, and the panel's
              own headline said the same thing again in different words. */}
          <RuleHealth coverage={coverage} headless />
        </div>
      )}
    </div>
  );
}

/**
 * The conditions the results were produced under.
 *
 * Each of these was a full-width alert competing with the run result. They are
 * standing facts about the environment rather than anything that just happened,
 * so they belong in one quiet line under everything.
 */
function ContextStrip({
  run,
  drift,
  captured,
}: {
  run: SyntheticRun | null;
  drift: DriftReport | null;
  captured: CaptureResult | null;
}) {
  const notes: ReactNode[] = [];

  if (run && run.enforcement_enabled === false) {
    notes.push(
      <>
        Enforcement is off, so a rule asking for WARN records a FLAG and notifies
        nobody
      </>,
    );
  }
  if (drift && !drift.available) {
    notes.push(<>the field catalogue is unchecked until a scan runs</>);
  }
  if (drift?.available && drift.total === 0) {
    notes.push(<>the field catalogue matches the last scan</>);
  }
  if (captured) {
    notes.push(
      captured.count === 0 ? (
        <>nothing to capture, because no scan has recorded any resources yet</>
      ) : (
        <>
          {captured.count} captured test{captured.count === 1 ? "" : "s"} written
          to your working copy, uncommitted
        </>
      ),
    );
  }

  if (!notes.length) return null;

  return (
    <p className="text-2xs leading-relaxed text-content-subtle">
      {notes.map((note, index) => (
        <span key={index}>
          {index > 0 && " · "}
          {note}
        </span>
      ))}
      .
    </p>
  );
}

function FixtureRow({
  fixture,
  result,
}: {
  fixture: SyntheticFixture;
  result?: SyntheticResult;
}) {
  // Null means "nobody has said", which lets a failure open itself while an
  // explicit collapse still sticks. A boolean plus an effect would reopen the
  // row every time results arrived, including the ones just closed.
  const [toggled, setToggled] = useState<boolean | null>(null);

  const state = !result ? "idle" : result.passed ? "pass" : "fail";
  const open = toggled ?? state === "fail";

  return (
    <Card
      className={cn(
        state === "fail" && "border-danger/40",
        state === "pass" && "border-success/30",
      )}
    >
      <CardHeader
        className="cursor-pointer select-none"
        onClick={() => setToggled(!open)}
      >
        <div className="flex items-start gap-2">
          {open ? (
            <ChevronDown className="mt-0.5 size-4 shrink-0 text-content-subtle" />
          ) : (
            <ChevronRight className="mt-0.5 size-4 shrink-0 text-content-subtle" />
          )}

          <div className="min-w-0 flex-1">
            <CardTitle className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[13px]">{fixture.name}</span>
              <Badge variant="outline">{fixture.resource_type}</Badge>
              {fixture.source === "captured" && (
                <Badge variant="info" title="Taken from a real scan">
                  captured
                </Badge>
              )}
              {state === "pass" && (
                <Badge variant="success">
                  <CheckCircle2 /> pass
                </Badge>
              )}
              {state === "fail" && (
                <Badge variant="danger">
                  <XCircle /> fail
                </Badge>
              )}
            </CardTitle>
            {fixture.description && (
              <p className="mt-1 text-xs text-content-muted">
                {fixture.description}
              </p>
            )}
          </div>
        </div>
      </CardHeader>

      {open && (
        <CardContent className="flex flex-col gap-3 border-t border-border pt-3">
          <Expectations fixture={fixture} />
          {result && <Outcome result={result} />}
        </CardContent>
      )}
    </Card>
  );
}

function Expectations({ fixture }: { fixture: SyntheticFixture }) {
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
      <div>
        <span className="text-content-subtle">Should fire: </span>
        {fixture.expects_fires.length ? (
          fixture.expects_fires.map((r) => (
            <code key={r} className="mr-1 text-warning">
              {r}
            </code>
          ))
        ) : (
          <span className="text-content-muted">nothing</span>
        )}
      </div>
      <div>
        <span className="text-content-subtle">Should pass: </span>
        {fixture.expects_passes.length ? (
          fixture.expects_passes.map((r) => (
            <code key={r} className="mr-1 text-success">
              {r}
            </code>
          ))
        ) : (
          <span className="text-content-muted">unspecified</span>
        )}
      </div>
    </div>
  );
}

/**
 * The four ways a fixture disagrees with the policies.
 *
 * They are listed separately rather than as one "failed" list because they mean
 * different things, and one of them is far worse than the others: a rule that
 * was expected to fire and did not is a policy that is not protecting anything,
 * and it looks identical to a clean result on the dashboard.
 */
const PROBLEMS: {
  key: keyof Pick<
    SyntheticResult,
    "missing" | "wrongly_fired" | "unexpected" | "not_evaluated"
  >;
  title: string;
  detail: string;
  tone: "danger" | "warning";
}[] = [
  {
    key: "missing",
    title: "Expected to fire, did not",
    detail:
      "The rule is silent on a resource that should trip it. On a real scan this reads as compliant.",
    tone: "danger",
  },
  {
    key: "wrongly_fired",
    title: "Expected to pass, fired",
    detail: "A false positive: the rule flags something the test says is fine.",
    tone: "warning",
  },
  {
    key: "unexpected",
    title: "Fired without being expected to",
    detail:
      "Either the rule is too broad or the test is out of date. Worth deciding which.",
    tone: "warning",
  },
  {
    key: "not_evaluated",
    title: "Named but never evaluated",
    detail:
      "No policy produced a result for this rule. Usually a typo in the test, or a rule that no longer exists.",
    tone: "warning",
  },
];

function Outcome({ result }: { result: SyntheticResult }) {
  if (result.error) {
    return <ErrorState message={result.error} />;
  }

  const problems = PROBLEMS.filter((p) => result[p.key].length > 0);

  return (
    <div className="flex flex-col gap-3">
      {problems.map((problem) => (
        <Alert key={problem.key} tone={problem.tone} title={problem.title}>
          <p className="mb-1">{problem.detail}</p>
          {result[problem.key].map((rule) => (
            <code key={rule} className="mr-1 font-mono text-2xs">
              {rule}
            </code>
          ))}
        </Alert>
      ))}

      {!!result.rules.length && (
        <div className="overflow-hidden rounded-md border border-border">
          <table className="w-full text-left text-xs">
            <thead className="bg-surface-raised text-2xs uppercase tracking-wide text-content-subtle">
              <tr>
                <th className="px-3 py-1.5 font-medium">Rule</th>
                <th className="px-3 py-1.5 font-medium">Result</th>
                <th className="px-3 py-1.5 font-medium">Asked for</th>
                <th className="px-3 py-1.5 font-medium">Would happen</th>
                <th className="px-3 py-1.5 font-medium">Message</th>
              </tr>
            </thead>
            <tbody>
              {result.rules.map((rule) => (
                <tr key={rule.rule_id} className="border-t border-border">
                  <td className="whitespace-nowrap px-3 py-1.5 font-mono">
                    {rule.rule_id}
                  </td>
                  <td className="px-3 py-1.5">
                    {rule.waived ? (
                      <Badge variant="neutral">waived</Badge>
                    ) : rule.violated ? (
                      <Badge variant="warning">
                        <AlertTriangle /> fired
                      </Badge>
                    ) : (
                      <Badge variant="success">passed</Badge>
                    )}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-content-muted">
                    {rule.requested_action ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 font-mono">
                    {rule.effective_action ? (
                      <span
                        className={cn(
                          rule.downgraded && "text-content-muted",
                        )}
                        title={rule.downgrade_reason ?? undefined}
                      >
                        {rule.effective_action}
                        {rule.downgraded && " (downgraded)"}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-content-muted">
                    {rule.message ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// --- pytest -----------------------------------------------------------------

function PytestPanel() {
  const [suite, setSuite] = useState("all");
  const [keyword, setKeyword] = useState("");
  const [suites, setSuites] = useState<
    { name: string; path: string; available: boolean }[]
  >([]);
  const [run, setRun] = useState<PytestRun | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassing, setShowPassing] = useState(false);

  useEffect(() => {
    api.testing
      .suites()
      .then((d) => setSuites(d.suites))
      .catch(() => setSuites([]));
  }, []);

  const start = async () => {
    setRunning(true);
    setError(null);
    setRun(null);
    try {
      setRun(
        await api.testing.pytest({
          suite,
          keyword: keyword.trim() || undefined,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const shown = useMemo(() => {
    if (!run) return [];
    return showPassing
      ? run.tests
      : run.tests.filter((t) => t.outcome !== "passed");
  }, [run, showPassing]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="w-44">
          <Select
            value={suite}
            onChange={(e) => setSuite(e.target.value)}
            disabled={running}
          >
            {(suites.length
              ? suites
              : [{ name: "all", path: "tests", available: true }]
            ).map((s) => (
              <option key={s.name} value={s.name} disabled={!s.available}>
                {s.name}
                {s.available ? "" : " (not installed)"}
              </option>
            ))}
          </Select>
        </div>

        <div className="w-56">
          <Input
            placeholder="Filter, e.g. chokepoint"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            disabled={running}
          />
        </div>

        <Button onClick={start} disabled={running}>
          {running ? <Spinner /> : <TerminalSquare />}
          {running ? "Running…" : "Run"}
        </Button>

        {run && (
          <div className="ml-auto flex items-center gap-2">
            <Badge variant={run.ok ? "success" : "danger"} size="md">
              {run.ok ? <CheckCircle2 /> : <XCircle />}
              {run.passed} passed
              {run.failed ? `, ${run.failed} failed` : ""}
              {run.skipped ? `, ${run.skipped} skipped` : ""}
            </Badge>
            <span className="text-xs text-content-subtle">
              {run.duration_seconds}s
            </span>
          </div>
        )}
      </div>

      {running && (
        <p className="text-[13px] text-content-muted">
          The full suite takes about half a minute. It runs in a separate
          process, so nothing here is affected by it.
        </p>
      )}

      {error && <ErrorState message={error} onRetry={() => void start()} />}

      {run?.error && (
        <Alert tone="danger" title="Nothing ran">
          {run.error}
        </Alert>
      )}

      {/* An empty region under a Run button reads as something broken. Nothing
          has happened yet, and saying so costs one line. */}
      {!run && !running && !error && (
        <EmptyState
          icon={<TerminalSquare className="size-6" />}
          title="Nothing has run yet"
          description={
            <>
              Press Run to execute the application's own test suite in a
              separate process. <code>safety</code> is the one that matters
              most — it holds the tests that stop a careless change making this
              system destructive.
            </>
          }
          action={
            <Button onClick={start}>
              <TerminalSquare />
              Run {suite}
            </Button>
          }
        />
      )}

      {run && !run.error && (
        <>
          <label className="flex w-fit cursor-pointer items-center gap-2 text-xs text-content-muted">
            <input
              type="checkbox"
              checked={showPassing}
              onChange={(e) => setShowPassing(e.target.checked)}
            />
            Show passing tests ({run.passed})
          </label>

          {!shown.length ? (
            <EmptyState
              icon={<CheckCircle2 className="size-6 text-success" />}
              title="Everything passed"
              description={`${run.total} tests in ${run.duration_seconds}s.`}
            />
          ) : (
            <div className="flex flex-col gap-1">
              {shown.map((test) => (
                <TestRow key={`${test.classname}::${test.name}`} test={test} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

const OUTCOME_BADGE = {
  passed: "success",
  failed: "danger",
  error: "danger",
  skipped: "neutral",
} as const;

function TestRow({ test }: { test: PytestRun["tests"][number] }) {
  const [open, setOpen] = useState(false);
  const hasDetail = Boolean(test.detail);

  return (
    <div className="rounded-md border border-border bg-surface">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left"
        onClick={() => hasDetail && setOpen((v) => !v)}
      >
        <Badge variant={OUTCOME_BADGE[test.outcome]}>{test.outcome}</Badge>
        <span className="min-w-0 flex-1 truncate font-mono text-xs">
          <span className="text-content-subtle">{test.classname}</span>
          <span className="text-content">::{test.name}</span>
        </span>
        <span className="shrink-0 text-2xs text-content-subtle">
          {test.time.toFixed(2)}s
        </span>
      </button>

      {open && test.detail && (
        <pre className="overflow-x-auto border-t border-border px-3 py-2 text-2xs text-content-muted">
          {test.detail}
        </pre>
      )}
    </div>
  );
}
