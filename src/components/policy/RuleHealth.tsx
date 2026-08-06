import { useState } from "react";
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

/**
 * Categories where the next move is not writing code.
 *
 * Worth separating visually: the first three groups are a queue of work, and
 * these two are not. Showing them in the same tone as a fixable bug is how a
 * rule that needs a metastore admin's signature sits in an engineering backlog
 * for a year.
 */
const NOT_OUR_MOVE: RuleCategory[] = ["needs_permission", "not_exposed"];

export function RuleHealth({
  coverage,
  onSelectRule,
  compact = false,
}: {
  coverage: CoverageReport;
  /** Optional: jump to a rule. The dashboard has nowhere to jump to. */
  onSelectRule?: (ruleId: string) => void;
  compact?: boolean;
}) {
  if (!coverage.total) return null;

  const broken = coverage.by_category.suspect ?? 0;
  const notWorking = coverage.total - coverage.reachable;
  const blocked = NOT_OUR_MOVE.reduce(
    (sum, category) => sum + (coverage.by_category[category] ?? 0),
    0,
  );

  if (!notWorking) {
    return (
      <Alert tone="success" title="Every rule has been shown working">
        All {coverage.total} rules have a test that makes them fire on data the
        scanner can really produce.
      </Alert>
    );
  }

  return (
    <Alert
      tone={broken ? "danger" : "warning"}
      title={`${coverage.reachable} of ${coverage.total} rules have been shown to work`}
    >
      <p className={compact ? "mb-2" : "mb-3"}>
        A rule that has never been shown working is not the same as a rule that
        found nothing wrong, but they look identical on a results page. These{" "}
        {notWorking} are not all the same problem, and they do not all have the
        same fix.
        {blocked > 0 && (
          <>
            {" "}
            {blocked} of them are waiting on somebody&rsquo;s permission, or on a
            decision to retire the rule, rather than on any code.
          </>
        )}
      </p>

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
            />
          );
        })}
      </div>

      {!compact && coverage.blocked_on.length > 0 && (
        <BlockedFields coverage={coverage} />
      )}
    </Alert>
  );
}

function CategoryRow({
  category,
  count,
  coverage,
  onSelectRule,
}: {
  category: RuleCategory;
  count: number;
  coverage: CoverageReport;
  onSelectRule?: (ruleId: string) => void;
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
                        Needs{" "}
                        <span className="font-semibold text-content">
                          {blocker.requirement}
                        </span>
                        . {blocker.detail}
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
