import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  FlaskConical,
  Play,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Alert, EmptyState, ErrorState, Spinner } from "../ui/feedback";
import { RuleHealth } from "./RuleHealth";
import api, {
  type CoverageReport,
  type SyntheticResult,
  type SyntheticRun,
} from "../../services/api";
import { usePolicyStore } from "../../store/policyStore";
import { cn } from "../../lib/utils";

/**
 * Testing the policy you have open, without leaving it.
 *
 * The loop this closes: ask the assistant, take its diff, then find out whether
 * the thing actually fires. Until now that last step meant going to another
 * page, and the run there evaluates the *committed* file — so anyone testing
 * midway through an edit was told about a version of the policy they had
 * already changed.
 *
 * Two questions get answered, and the second is the one people forget. "Do the
 * fixtures pass" is the obvious one. "Is this rule covered by any fixture at
 * all" is the one that matters, because an untested rule and a working rule
 * look exactly the same on a green page.
 */
export function PolicyTestsPanel({
  policyName,
  resourceType,
  ruleIds,
}: {
  policyName?: string;
  resourceType?: string;
  ruleIds: string[];
}) {
  const store = usePolicyStore();
  const [coverage, setCoverage] = useState<CoverageReport | null>(null);
  const [run, setRun] = useState<SyntheticRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = store.isDirty();

  const load = useCallback(async () => {
    if (!policyName) return;
    setLoading(true);
    setError(null);
    try {
      setCoverage(await api.testing.coverage({ policy: policyName }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [policyName]);

  useEffect(() => {
    setRun(null);
    void load();
  }, [load]);

  const start = async () => {
    if (!policyName) return;
    setRunning(true);
    setError(null);
    try {
      setRun(
        await api.testing.synthetic({
          resource_type: resourceType,
          // The draft, always. Testing what is on disk while the editor holds
          // something else is how you get a green run for a change that was
          // never exercised.
          draft_policy: policyName,
          draft_content: store.content,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const mine = useMemo(
    () => new Set(ruleIds),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ruleIds.join(",")],
  );

  const uncovered = coverage?.rules.filter((r) => !r.covered) ?? [];
  const noNegative = coverage?.rules.filter(
    (r) => r.covered && !r.has_negative_case,
  ) ?? [];
  const fakeCovered = coverage?.rules.filter(
    (r) => r.covered && !r.reachable,
  ) ?? [];

  if (!policyName) {
    return (
      <EmptyState
        icon={<FlaskConical className="size-6" />}
        title="No policy open"
        description="Pick a policy to see what its rules are tested against."
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-3 border-b border-border p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={start} loading={running} disabled={running}>
            <Play />
            {running ? "Running…" : "Run the fixtures"}
          </Button>

          {resourceType && (
            <Badge variant="outline">{resourceType} fixtures</Badge>
          )}

          {run && (
            <Badge
              variant={run.failed ? "danger" : run.total ? "success" : "warning"}
              size="md"
              className="ml-auto"
            >
              {run.failed ? <XCircle /> : <CheckCircle2 />}
              {run.total
                ? `${run.passed} of ${run.total} passing`
                : "no fixtures ran"}
            </Badge>
          )}
        </div>

        <p className="text-2xs text-content-subtle">
          Runs what is in the editor right now against made-up resources, using
          the real policies and the real action ladder. Nothing reaches a
          workspace.{" "}
          {dirty && (
            <span className="text-warning">
              Your unsaved changes are what gets tested.
            </span>
          )}
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {error && <ErrorState message={error} onRetry={() => void load()} />}

        {loading && !coverage ? (
          <div className="flex items-center gap-2 text-2xs text-content-subtle">
            <Spinner className="size-3" /> Checking coverage…
          </div>
        ) : (
          coverage && (
            <Coverage
              coverage={coverage}
              uncovered={uncovered}
              noNegative={noNegative}
              fakeCovered={fakeCovered}
            />
          )
        )}

        {run && run.total === 0 && (
          <Alert tone="warning" title="Nothing was tested">
            There are no fixtures for{" "}
            <code>{resourceType ?? "this resource type"}</code>, so this run
            checked nothing. Add one in the{" "}
            <Link to="/testing" className="underline underline-offset-2">
              Testing Center
            </Link>{" "}
            or capture some from a scan.
          </Alert>
        )}

        {run?.results.map((result) => (
          <FixtureResult
            key={result.fixture}
            result={result}
            mine={mine}
          />
        ))}
      </div>
    </div>
  );
}

function Coverage({
  coverage,
  uncovered,
  noNegative,
  fakeCovered,
}: {
  coverage: CoverageReport;
  uncovered: CoverageReport["rules"];
  noNegative: CoverageReport["rules"];
  fakeCovered: CoverageReport["rules"];
}) {
  if (!coverage.total) {
    return null;
  }

  return (
    <section className="space-y-2">
      {fakeCovered.length > 0 && (
        <Alert
          tone="danger"
          title={`${fakeCovered.length} rule${fakeCovered.length === 1 ? " passes" : "s pass"} on invented data`}
        >
          <p className="mb-2">
            The only fixture that makes{" "}
            {fakeCovered.length === 1 ? "this rule" : "these rules"} fire sets a
            field no handler collects. It passes here and does nothing at all
            against a real workspace.
          </p>
          <ul className="space-y-1">
            {fakeCovered.map((rule) => (
              <li key={rule.rule_id} className="text-2xs">
                <code className="font-mono">{rule.rule_id}</code>
                {rule.title && (
                  <span className="text-content-muted"> — {rule.title}</span>
                )}
              </li>
            ))}
          </ul>
        </Alert>
      )}

      {/* Compact: this panel is a column beside the code, and the list of
          fields worth collecting is an estate-wide question rather than one
          about the policy that happens to be open. */}
      <RuleHealth coverage={coverage} compact />

      {noNegative.length > 0 && (
        <Alert
          tone="info"
          title={`${noNegative.length} rule${noNegative.length === 1 ? "" : "s"} only ever tested firing`}
        >
          No fixture shows{" "}
          {noNegative.length === 1 ? "this rule" : "these rules"} leaving a
          compliant resource alone, which is how a rule that is too broad gets
          through.{" "}
          {noNegative.map((rule) => (
            <code key={rule.rule_id} className="mr-1 font-mono text-2xs">
              {rule.rule_id}
            </code>
          ))}
        </Alert>
      )}

      {!uncovered.length && !noNegative.length && !fakeCovered.length && (
        <p className="flex items-center gap-1.5 text-2xs text-success">
          <CheckCircle2 className="size-3.5" aria-hidden />
          Every rule in this policy has a fixture that expects it to fire and one
          that expects it not to.
        </p>
      )}
    </section>
  );
}

function FixtureResult({
  result,
  mine,
}: {
  result: SyntheticResult;
  mine: Set<string>;
}) {
  // Rules from other policies are evaluated too, since a fixture runs the whole
  // namespace. They are not what this panel is about, so they stay out of the
  // way unless one of them broke.
  const rules = result.rules.filter((r) => mine.has(r.rule_id));
  const problems = [
    ...result.missing.map((r) => ({ rule: r, kind: "did not fire" as const })),
    ...result.wrongly_fired.map((r) => ({ rule: r, kind: "fired wrongly" as const })),
    ...result.unexpected.map((r) => ({ rule: r, kind: "unexpected" as const })),
  ].filter((p) => mine.has(p.rule));

  if (!rules.length && !problems.length) return null;

  return (
    <section
      className={cn(
        "rounded-md border bg-surface-raised p-3",
        result.passed ? "border-border" : "border-danger/40",
      )}
    >
      <div className="mb-2 flex items-center gap-2">
        {result.passed ? (
          <CheckCircle2 className="size-3.5 shrink-0 text-success" aria-hidden />
        ) : (
          <ShieldAlert className="size-3.5 shrink-0 text-danger" aria-hidden />
        )}
        <span className="font-mono text-2xs text-content">{result.fixture}</span>
      </div>

      {result.error && <ErrorState message={result.error} />}

      {problems.length > 0 && (
        <ul className="mb-2 space-y-1">
          {problems.map(({ rule, kind }) => (
            <li key={`${rule}-${kind}`} className="text-2xs text-danger">
              <code className="font-mono">{rule}</code> {kind}
            </li>
          ))}
        </ul>
      )}

      <div className="space-y-1">
        {rules.map((rule) => (
          <div key={rule.rule_id} className="flex items-center gap-2 text-2xs">
            {rule.violated ? (
              <AlertTriangle className="size-3 shrink-0 text-warning" aria-hidden />
            ) : (
              <CheckCircle2 className="size-3 shrink-0 text-success" aria-hidden />
            )}
            <code className="font-mono text-content">{rule.rule_id}</code>
            <span className="text-content-subtle">
              {rule.waived
                ? "waived by an exception"
                : rule.violated
                  ? `fires — would ${rule.effective_action}`
                  : "passes"}
            </span>
            {rule.downgraded && (
              <Badge variant="neutral" title={rule.downgrade_reason ?? undefined}>
                downgraded from {rule.requested_action}
              </Badge>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
