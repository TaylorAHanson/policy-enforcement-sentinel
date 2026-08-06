import { useMemo, useState } from "react";
import { Plus, Search, X } from "lucide-react";
import { Badge, SeverityBadge } from "../ui/badge";
import { Button } from "../ui/button";
import { Alert, EmptyState } from "../ui/feedback";
import { Input, Select } from "../ui/input";
import { TierBadge } from "../safety/TierBadge";
import { humanize } from "../../lib/utils";
import type { PolicyMetadata, PolicyRule } from "../../services/api";

/**
 * Below this, a filter bar costs more attention than it saves — every rule is
 * already on screen, and the controls are just chrome above a list you can read
 * in one look.
 */
const FILTER_THRESHOLD = 4;

/**
 * The policy's annotations and per-rule metadata, read back from OPA rather
 * than from the editor buffer. That distinction matters: this shows what the
 * engine will actually evaluate, so it reflects the last saved version and not
 * whatever is currently being typed.
 */
export function PolicyMetadataPanel({
  metadata,
  dirty,
  onAddRule,
}: {
  metadata: PolicyMetadata | null;
  dirty: boolean;
  /** Hand a half-written request to the assistant. See `AddRuleButton`. */
  onAddRule?: (seed: string) => void;
}) {
  if (!metadata) {
    return (
      <EmptyState
        title="No metadata"
        description="This policy has no METADATA annotations or rule_metadata block, or it does not currently compile."
      />
    );
  }

  const escalated = metadata.rules.filter((r) => r.tier >= 2);

  return (
    <div className="space-y-4 p-4">
      {dirty && (
        <Alert tone="info" title="Showing the saved version">
          You have unsaved edits. This panel reflects what OPA has loaded, which
          updates when you save.
        </Alert>
      )}

      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-content">{metadata.title}</h3>
        {metadata.description && (
          <p className="whitespace-pre-line text-xs leading-relaxed text-content-muted">
            {metadata.description}
          </p>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-border bg-surface-raised px-4 py-3 text-xs">
        <Meta label="Owner" value={metadata.owner || "—"} />
        <Meta label="Domain" value={humanize(metadata.domain) || "—"} />
        <Meta label="Resource type" value={humanize(metadata.resource_type) || "—"} />
        <Meta label="Rules" value={String(metadata.rule_count)} />
        {metadata.authors.length > 0 && (
          <div className="col-span-2">
            <dt className="text-2xs uppercase tracking-wider text-content-subtle">
              Authors
            </dt>
            <dd className="mt-0.5 text-content">{metadata.authors.join(", ")}</dd>
          </div>
        )}
      </dl>

      {escalated.length > 0 && (
        // Worth calling out loudly. Everything ships at Tier 1, so a Tier 2+
        // rule means somebody deliberately escalated it and the reviewer of
        // this policy should know without reading all sixty lines of metadata.
        <Alert
          tone={escalated.some((r) => r.tier >= 3) ? "danger" : "warning"}
          title={`${escalated.length} rule${escalated.length === 1 ? "" : "s"} escalated beyond notify`}
        >
          {escalated.map((r) => r.id).join(", ")} can change or remove resources.
        </Alert>
      )}

      <RulesList
        rules={metadata.rules}
        resourceType={metadata.resource_type}
        onAddRule={onAddRule}
      />
    </div>
  );
}

/**
 * A list with no way to add to it invites the question, so answer it.
 *
 * There is no form behind this, and there could not usefully be one: a rule is
 * a Rego expression, and the interesting part — which fields to test and how —
 * is exactly the part a form cannot capture. But "you cannot add a rule here"
 * is also false, so the button exists and does the thing that actually works,
 * which is to start the conversation that writes it.
 *
 * The seed carries the resource type, because the first thing the assistant
 * needs to know is which handler's fields are available, and a request that
 * omits it gets a rule reading data nobody collects.
 */
function AddRuleButton({
  resourceType,
  onAddRule,
}: {
  resourceType?: string;
  onAddRule: (seed: string) => void;
}) {
  const subject = resourceType ? resourceType.replace(/_/g, " ") : "resource";
  const article = /^[aeiou]/i.test(subject) ? "an" : "a";

  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={() =>
        onAddRule(
          `Add a rule to this policy that flags ${article} ${subject} when `,
        )
      }
      title={
        "Rules are Rego, so there is no form for this. Opens the assistant " +
        "with the request started, and its proposal lands as a diff you review."
      }
    >
      <Plus />
      Add a rule
    </Button>
  );
}

function RulesList({
  rules,
  resourceType,
  onAddRule,
}: {
  rules: PolicyRule[];
  resourceType?: string;
  onAddRule?: (seed: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");

  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    rules.forEach((rule) => {
      if (rule.category) {
        counts.set(rule.category, (counts.get(rule.category) ?? 0) + 1);
      }
    });
    return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [rules]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rules.filter((rule) => {
      if (category && rule.category !== category) return false;
      if (!needle) return true;
      // The rule's own identifiers and prose, plus the words people actually
      // search these by — "destructive" and "terminate" are how you find the
      // rules worth worrying about, and neither is in the description.
      return [
        rule.id,
        rule.rule,
        rule.description,
        rule.category,
        rule.severity,
        rule.requested_action,
        rule.destructive ? "destructive" : "",
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [rules, query, category]);

  const filtering = Boolean(query.trim() || category);
  const showControls = rules.length >= FILTER_THRESHOLD;

  const clear = () => {
    setQuery("");
    setCategory("");
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h4 className="text-2xs font-semibold uppercase tracking-wider text-content-subtle">
          Rules
        </h4>
        <Badge variant="outline">
          {filtering ? `${visible.length} of ${rules.length}` : rules.length}
        </Badge>
        {filtering && (
          <Button variant="ghost" size="sm" onClick={clear}>
            <X />
            Clear
          </Button>
        )}

        {onAddRule && (
          <div className="ml-auto">
            <AddRuleButton
              resourceType={resourceType}
              onAddRule={onAddRule}
            />
          </div>
        )}
      </div>

      {showControls && (
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[12rem] flex-1">
            <Search
              className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-content-subtle"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search rules"
              aria-label="Search rules"
              className="pl-8"
            />
          </div>

          {categories.length > 1 && (
            <Select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              aria-label="Filter by category"
              className="w-auto"
            >
              <option value="">All categories</option>
              {categories.map(([name, count]) => (
                <option key={name} value={name}>
                  {humanize(name)} ({count})
                </option>
              ))}
            </Select>
          )}
        </div>
      )}

      {visible.length === 0 ? (
        <EmptyState
          title="No rule matches"
          description={
            category && query.trim()
              ? `Nothing in ${humanize(category)} matches “${query.trim()}”.`
              : "Try a different search, or clear the filters."
          }
          action={
            <Button variant="secondary" size="sm" onClick={clear}>
              Clear filters
            </Button>
          }
        />
      ) : (
        visible.map((rule) => (
          <div
            key={rule.rule}
            className="rounded-md border border-border bg-surface-raised px-3 py-2.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <code className="font-mono text-xs text-content">{rule.id}</code>
              <SeverityBadge severity={rule.severity} />
              <button
                type="button"
                // Clicking a category filters to it, which is the thing you
                // want the moment you notice one and is otherwise a trip to the
                // dropdown to retype what is already on screen.
                onClick={() =>
                  setCategory((c) => (c === rule.category ? "" : rule.category))
                }
                title={
                  category === rule.category
                    ? "Show all categories"
                    : `Show only ${humanize(rule.category)}`
                }
              >
                <Badge variant={category === rule.category ? "info" : "outline"}>
                  {humanize(rule.category)}
                </Badge>
              </button>
              <span className="flex-1" />
              <code className="font-mono text-2xs text-content-muted">
                {rule.requested_action}
              </code>
              <TierBadge tier={rule.tier} />
              {rule.destructive && <Badge variant="danger">destructive</Badge>}
            </div>
            <p className="mt-1.5 text-2xs leading-relaxed text-content-muted">
              {rule.description}
            </p>
            <div className="mt-1 flex items-center gap-3 text-2xs text-content-subtle">
              <code className="font-mono">{rule.rule}</code>
              {rule.escalate_after_days > 0 && (
                <span>escalates after {rule.escalate_after_days} days</span>
              )}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-2xs uppercase tracking-wider text-content-subtle">{label}</dt>
      <dd className="mt-0.5 text-content">{value}</dd>
    </div>
  );
}
