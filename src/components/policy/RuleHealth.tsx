import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Lock, Wrench } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Alert } from "../ui/feedback";
import { cn } from "../../lib/utils";
import type { CoverageReport, RuleCategory } from "../../services/api";

/**
 * How many rules work, and for the rest, what would actually make them work.
 *
 * This replaced a sentence that was accurate and useless: "41 rules have no
 * fixture that makes them fire". It named the mechanism rather than the
 * problem, and it presented one number where there are three separate
 * situations with three different people who could act on them.
 *
 * The order below is the order to work through, not the size of each group.
 * "Probably broken" is first because it is the only category that is likely an
 * outright bug, and the only one somebody can fix without either writing a
 * handler or deciding what discovery should collect.
 */
const ORDER: RuleCategory[] = [
  "suspect",
  "untested",
  "needs_discovery",
  "needs_permission",
  "not_exposed",
  "no_handler",
];

const TONE: Record<RuleCategory, string> = {
  suspect: "text-danger",
  untested: "text-warning",
  needs_discovery: "text-warning",
  needs_permission: "text-content-muted",
  not_exposed: "text-content-muted",
  no_handler: "text-content-muted",
  working: "text-success",
};

/** "a, b and c" — the counts read as prose, so they should punctuate like it. */
function sentence(parts: ReactNode[]): ReactNode {
  return parts.map((part, index) => (
    <span key={index}>
      {index > 0 && (index === parts.length - 1 ? " and " : ", ")}
      {part}
    </span>
  ));
}

export function RuleHealth({
  coverage,
  onSelectRule,
  compact = false,
  headless = false,
}: {
  coverage: CoverageReport;
  /** Optional: jump to a rule. The dashboard has nowhere to jump to. */
  onSelectRule?: (ruleId: string) => void;
  compact?: boolean;
  /**
   * Drop the alert frame and the headline, for a caller that already states
   * the count. The Testing Center's fold is labelled "45 of 64 rules proven";
   * repeating "45 of 64 rules have been shown to work" directly beneath it,
   * inside a red box, is the same number twice in two phrasings — which is
   * most of what made this panel read as an error rather than a report.
   */
  headless?: boolean;
}) {
  if (!coverage.total) return null;

  const broken = coverage.by_category.suspect ?? 0;
  const notWorking = coverage.total - coverage.reachable;

  if (!notWorking) {
    if (headless) return null;
    return (
      <Alert tone="success" title="Every rule has been shown working">
        All {coverage.total} rules have a test that makes them fire on data the
        scanner can really produce.
      </Alert>
    );
  }

  const body = (
    <>
      {!headless && (
        <p className={compact ? "mb-2" : "mb-3"}>
          {notWorking} have never been shown working, which is not the same as
          finding nothing wrong &mdash; the two look identical on a results
          page. <Summary coverage={coverage} />
        </p>
      )}

      {!compact && coverage.asks.length > 0 && <AccessAsks coverage={coverage} />}

      <div className="space-y-1.5">
        {ORDER.map((category) => {
          const count = coverage.by_category[category] ?? 0;
          if (!count) return null;
          return (
            <CategoryRow
              key={category}
              category={category}
              count={count}
              coverage={coverage}
              onSelectRule={onSelectRule}
              showRequirement={compact || !coverage.asks.length}
            />
          );
        })}
      </div>

      {!compact && coverage.blocked_on.length > 0 && (
        <BlockedFields coverage={coverage} />
      )}
    </>
  );

  if (headless) return <div className="text-xs">{body}</div>;

  return (
    <Alert
      tone={broken ? "danger" : "warning"}
      title={`${coverage.reachable} of ${coverage.total} rules have been shown to work`}
    >
      {body}
    </Alert>
  );
}

/**
 * One clause per group, with numbers that add up to the ones below.
 *
 * The paragraph this replaced said "14 of them are waiting on somebody's
 * permission, or on a decision to retire the rule" — a number that matched no
 * group the reader could then see, describing two situations at once.
 */
function Summary({ coverage }: { coverage: CoverageReport }) {
  const count = (category: RuleCategory) => coverage.by_category[category] ?? 0;
  const clauses: ReactNode[] = [];

  const suspect = count("suspect");
  if (suspect) {
    clauses.push(
      suspect === 1 ? "one looks like a bug" : `${suspect} look like bugs`,
    );
  }

  const untested = count("untested");
  if (untested) {
    clauses.push(`${untested} ${untested === 1 ? "needs" : "need"} a test`);
  }

  const discovery = count("needs_discovery");
  if (discovery) {
    clauses.push(
      `${discovery} ${discovery === 1 ? "waits" : "wait"} on a field nothing collects yet`,
    );
  }

  const permission = count("needs_permission");
  if (permission && coverage.asks.length) {
    clauses.push(
      `${permission} ${permission === 1 ? "waits" : "wait"} on ${coverage.asks.length} access ${coverage.asks.length === 1 ? "grant" : "grants"}`,
    );
  }

  const noHandler = count("no_handler");
  if (noHandler) {
    const types = coverage.unscanned_types;
    clauses.push(
      <>
        {noHandler} {noHandler === 1 ? "needs" : "need"}{" "}
        {types.length === 1 ? "a" : ""}{" "}
        {sentence(
          types.map((type) => (
            <code key={type} className="font-mono">
              {type}
            </code>
          )),
        )}{" "}
        {types.length === 1 ? "handler" : "handlers"}
      </>,
    );
  }

  const notExposed = count("not_exposed");
  if (notExposed) {
    clauses.push(
      `${notExposed} ${notExposed === 1 ? "asks" : "ask"} for something Databricks does not publish`,
    );
  }

  if (!clauses.length) return null;
  return <>Of those, {sentence(clauses)}.</>;
}

/**
 * The permission-blocked rules folded into the grants that would release them.
 *
 * Ten rules each carrying "needs SELECT on the system catalog" is ten lines
 * saying one thing. Grouped, it is a short list of requests with a number
 * attached to each — which is the form in which somebody can take it to whoever
 * owns the metastore and get a yes or a no.
 */
function AccessAsks({ coverage }: { coverage: CoverageReport }) {
  const total = coverage.asks.reduce((sum, ask) => sum + ask.rule_count, 0);

  return (
    <div className="mb-3 rounded-md border border-border bg-surface-raised/50 px-2.5 py-2">
      <p className="mb-1.5 flex items-center gap-1.5 text-2xs font-semibold text-content">
        <Lock className="size-3 shrink-0" />
        {coverage.asks.length} {coverage.asks.length === 1 ? "grant" : "grants"}{" "}
        would turn on {total} {total === 1 ? "rule" : "rules"}
      </p>
      <ul className="space-y-1">
        {coverage.asks.map((ask) => (
          <li
            key={ask.requirement}
            className="flex items-baseline gap-2 text-2xs"
          >
            <Badge variant="outline">{ask.rule_count}</Badge>
            <span>
              <span className="font-medium text-content">{ask.requirement}</span>
              <span className="text-content-muted">
                {" "}
                &mdash; for{" "}
                {sentence(
                  ask.fields.map((field) => (
                    <code key={field} className="font-mono">
                      {field}
                    </code>
                  )),
                )}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CategoryRow({
  category,
  count,
  coverage,
  onSelectRule,
  showRequirement,
}: {
  category: RuleCategory;
  count: number;
  coverage: CoverageReport;
  onSelectRule?: (ruleId: string) => void;
  /** False when the grants panel above already names it, to stop it repeating. */
  showRequirement: boolean;
}) {
  const [open, setOpen] = useState(category === "suspect");
  const info = coverage.categories[category];
  const rules = coverage.rules.filter((rule) => rule.category === category);

  return (
    <div className="rounded-md border border-border bg-surface-raised/50">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-start gap-2 px-2.5 py-2 text-left"
      >
        {open ? (
          <ChevronDown className="mt-0.5 size-3.5 shrink-0 text-content-subtle" />
        ) : (
          <ChevronRight className="mt-0.5 size-3.5 shrink-0 text-content-subtle" />
        )}
        <div className="min-w-0 flex-1">
          <span className={cn("text-xs font-semibold", TONE[category])}>
            {count} {count === 1 ? "rule" : "rules"} · {info.label}
          </span>
          <p className="mt-0.5 text-2xs leading-relaxed text-content-muted">
            {info.detail}
            {category === "no_handler" && coverage.unscanned_types.length > 0 && (
              <>
                {" "}
                Nothing discovers{" "}
                {sentence(
                  coverage.unscanned_types.map((type) => (
                    <code key={type} className="font-mono text-content">
                      {type}
                    </code>
                  )),
                )}
                .
              </>
            )}
          </p>
        </div>
      </button>

      {open && (
        <div className="space-y-2 border-t border-border px-2.5 py-2">
          <p className="flex items-start gap-1.5 text-2xs text-content">
            <Wrench className="mt-0.5 size-3 shrink-0" />
            <span>
              <span className="font-semibold">What to do: </span>
              {info.action}
            </span>
          </p>
          <ul className="space-y-1">
            {rules.map((rule) => (
              <li key={rule.rule_id} className="text-2xs">
                {onSelectRule ? (
                  <button
                    type="button"
                    onClick={() => onSelectRule(rule.rule_id)}
                    className="font-mono underline underline-offset-2 hover:text-content"
                  >
                    {rule.rule_id}
                  </button>
                ) : (
                  <code className="font-mono">{rule.rule_id}</code>
                )}
                <span className="text-content-muted">
                  {" "}
                  — {rule.title}
                  {rule.missing_fields.length > 0 && (
                    <>
                      {" "}
                      Reads{" "}
                      {rule.missing_fields.map((field, index) => (
                        <span key={field}>
                          {index > 0 && ", "}
                          <code className="font-mono text-content">{field}</code>
                        </span>
                      ))}
                      .
                    </>
                  )}
                </span>
                {rule.blockers
                  .filter((blocker) => blocker.requirement)
                  .map((blocker) => (
                    <p
                      key={blocker.field}
                      className="mt-0.5 flex items-start gap-1.5 pl-1 text-2xs text-content-muted"
                    >
                      <Lock className="mt-0.5 size-3 shrink-0" />
                      <span>
                        {showRequirement && (
                          <>
                            Needs{" "}
                            <span className="font-semibold text-content">
                              {blocker.requirement}
                            </span>
                            .{" "}
                          </>
                        )}
                        {blocker.detail}
                      </span>
                    </p>
                  ))}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * One field, and how many rules start working if discovery collects it.
 *
 * This is the whole argument for a discovery change in one line. "Collect
 * idle_days and nine rules across nine resource types come alive" is a decision
 * somebody can weigh; "31 rules reference uncollected fields" is not.
 */
function BlockedFields({ coverage }: { coverage: CoverageReport }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? coverage.blocked_on : coverage.blocked_on.slice(0, 4);
  const rest = coverage.blocked_on.length - shown.length;

  return (
    <div className="mt-3 border-t border-border pt-2.5">
      <p className="mb-1.5 text-2xs font-semibold text-content">
        The fields worth collecting first
      </p>
      <ul className="space-y-1">
        {shown.map((entry) => (
          <li key={entry.field} className="flex items-baseline gap-2 text-2xs">
            <Badge variant="outline">{entry.rule_count}</Badge>
            <span>
              <code className="font-mono text-content">{entry.field}</code>
              <span className="text-content-muted">
                {" "}
                would unblock {entry.rule_count}{" "}
                {entry.rule_count === 1 ? "rule" : "rules"} across{" "}
                {entry.resource_types.length}{" "}
                {entry.resource_types.length === 1 ? "type" : "types"}:{" "}
                {entry.resource_types.join(", ")}
              </span>
            </span>
          </li>
        ))}
      </ul>
      {rest > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1"
          onClick={() => setExpanded(true)}
        >
          Show {rest} more
        </Button>
      )}
    </div>
  );
}
