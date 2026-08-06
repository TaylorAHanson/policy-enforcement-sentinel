import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react";

import api, {
  type AllowlistEntry,
  type AllowlistImpact,
  type AllowlistMatchType,
  type PolicyRegistry,
  type ResourceTypeOption,
} from "../services/api";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Dialog } from "../components/ui/dialog";
import { Alert, EmptyState, ErrorState, Spinner } from "../components/ui/feedback";
import { Field, Input, Label, Select } from "../components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "../components/ui/table";
import { cn } from "../lib/utils";
import { toast } from "../store/toastStore";

/** A sensible default that is still short enough to feel like a real decision. */
function defaultExpiry(): string {
  const date = new Date();
  date.setDate(date.getDate() + 90);
  return date.toISOString().slice(0, 10);
}

interface DraftState {
  match_type: AllowlistMatchType;
  resource_id: string;
  resource_type: string;
  rule_id: string;
  workspace: string;
  justification: string;
  expires_at: string;
}

const EMPTY_DRAFT: DraftState = {
  match_type: "resource",
  resource_id: "",
  resource_type: "",
  rule_id: "",
  workspace: "",
  justification: "",
  expires_at: "",
};

/**
 * Exceptions to the policies, in two shapes.
 *
 * A *resource* exception names one thing and waives every rule that fails for
 * it. A *pattern* waives one rule for one resource type in one workspace, which
 * is how people actually think — "service principals are allowed to own jobs in
 * the sandbox" is a sentence about a class.
 *
 * The page leans on the difference rather than hiding it. A pattern covers
 * resources that do not exist yet, so it is the only kind that can grow after
 * it is written, and the only kind whose growth is invisible: a suppressed
 * finding looks exactly like a resource that passed. Hence the count of what
 * each one is currently hiding, and the compulsory expiry.
 */
export default function Allowlist() {
  const [entries, setEntries] = useState<AllowlistEntry[]>([]);
  const [impact, setImpact] = useState<Record<string, AllowlistImpact>>({});
  const [resourceTypes, setResourceTypes] = useState<ResourceTypeOption[]>([]);
  const [registry, setRegistry] = useState<PolicyRegistry | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<DraftState>(EMPTY_DRAFT);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [rows, types] = await Promise.all([
        api.allowlist.list(),
        api.allowlist.resourceTypes(),
      ]);
      setEntries(rows);
      setResourceTypes(types);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }

    // Both are decoration on a page that works without them, so neither is
    // allowed to fail the load.
    void api.allowlist
      .impact()
      .then((rows) =>
        setImpact(Object.fromEntries(rows.map((row) => [row.id, row]))),
      )
      .catch(() => setImpact({}));
    void api.policies
      .registry()
      .then(setRegistry)
      .catch(() => setRegistry(null));
  };

  useEffect(() => {
    void load();
  }, []);

  /** Rules that could be waived, for the type the draft is about. */
  const rulesForType = useMemo(() => {
    if (!registry) return [];
    return registry.policies
      .filter((policy) => !draft.resource_type || policy.resource_type === draft.resource_type)
      .flatMap((policy) =>
        policy.rules.map((rule) => ({
          id: rule.id,
          label: `${rule.id} — ${rule.rule}`,
          policy: policy.name,
        })),
      );
  }, [registry, draft.resource_type]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((entry) =>
      [entry.resource_id, entry.rule_id, entry.resource_type, entry.workspace, entry.justification]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(needle)),
    );
  }, [entries, query]);

  const openForm = () => {
    setDraft({
      ...EMPTY_DRAFT,
      // The narrower of the two is the default. Someone who has not thought
      // about scope yet should get the exception that covers one resource, not
      // the one that covers a class.
      match_type: "resource",
      resource_type: resourceTypes[0]?.value ?? "",
      expires_at: "",
    });
    setAdding(true);
  };

  /**
   * Switching scope inside the form.
   *
   * A pattern must expire, so moving to one fills the date rather than letting
   * the form be submitted and rejected. Moving back leaves it alone: a date the
   * user typed is theirs, and a resource exception is allowed to have one.
   */
  const setScope = (match_type: AllowlistMatchType) => {
    setDraft((current) => ({
      ...current,
      match_type,
      expires_at:
        match_type === "pattern" && !current.expires_at
          ? defaultExpiry()
          : current.expires_at,
    }));
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      await api.allowlist.create({
        match_type: draft.match_type,
        resource_type: draft.resource_type,
        workspace: draft.workspace.trim(),
        justification: draft.justification.trim(),
        resource_id: draft.match_type === "resource" ? draft.resource_id.trim() : null,
        rule_id: draft.match_type === "pattern" ? draft.rule_id : null,
        expires_at: draft.expires_at ? new Date(draft.expires_at).toISOString() : null,
      });
      setAdding(false);
      toast.success("Exception added");
      void load();
    } catch (e) {
      toast.error(
        "Could not add the exception",
        e instanceof Error ? e.message : String(e),
      );
    } finally {
      setSaving(false);
    }
  };

  const remove = async (entry: AllowlistEntry) => {
    const covered = impact[entry.id]?.suppressed_findings ?? 0;
    const what =
      entry.match_type === "pattern"
        ? `${entry.rule_id} on every ${entry.resource_type} in ${entry.workspace}`
        : entry.resource_id;

    if (
      !confirm(
        `Remove the exception for ${what}?` +
          (covered ? `\n\n${covered} finding(s) it is hiding will reappear.` : ""),
      )
    ) {
      return;
    }

    try {
      await api.allowlist.remove(entry.id);
      toast.success("Exception removed");
      void load();
    } catch (e) {
      toast.error("Could not remove it", e instanceof Error ? e.message : String(e));
    }
  };

  const patternCount = entries.filter((e) => e.match_type === "pattern").length;
  const isPattern = draft.match_type === "pattern";

  if (error && !entries.length) {
    return <ErrorState message={error} onRetry={() => void load()} />;
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
        <div>
          <h1 className="text-lg font-semibold text-content">Exceptions</h1>
          <p className="mt-1 text-xs text-content-muted">
            Findings that have been agreed away. An exception suppresses a
            finding; it does not change what the policy checks.
          </p>
        </div>
        <Button variant="primary" onClick={openForm}>
          <Plus />
          Add an exception
        </Button>
      </header>

      {patternCount > 0 && (
        <Alert tone="warning" title={`${patternCount} class-wide exception${patternCount === 1 ? "" : "s"} in force`}>
          A pattern also covers resources created after it was written, so what
          it hides grows on its own. The counts below are from the most recent
          scan.
        </Alert>
      )}

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-border p-3">
          <div className="relative w-full max-w-sm">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-content-subtle" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search resource, rule, workspace or reason"
              className="pl-8"
            />
          </div>
          <Button variant="ghost" size="sm" onClick={() => void load()} title="Refresh">
            <RefreshCw className={loading ? "animate-spin" : ""} />
          </Button>
        </div>

        {loading && !entries.length ? (
          <div className="flex items-center justify-center gap-2 p-10 text-xs text-content-muted">
            <Spinner className="size-4" />
            Loading exceptions
          </div>
        ) : !filtered.length ? (
          <EmptyState
            icon={<ShieldCheck className="size-8" />}
            title={entries.length ? "Nothing matches that search" : "No exceptions"}
            description={
              entries.length
                ? "Try a shorter search."
                : "Every finding is currently being reported. Add an exception when a rule is knowingly not worth acting on."
            }
          />
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>Scope</TableHeaderCell>
                <TableHeaderCell>Workspace</TableHeaderCell>
                <TableHeaderCell>Hiding</TableHeaderCell>
                <TableHeaderCell>Expires</TableHeaderCell>
                <TableHeaderCell>Reason</TableHeaderCell>
                <TableHeaderCell className="text-right">Actions</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.map((entry) => (
                <ExceptionRow
                  key={entry.id}
                  entry={entry}
                  impact={impact[entry.id]}
                  onRemove={() => void remove(entry)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <Dialog
        open={adding}
        onClose={() => setAdding(false)}
        title="Add an exception"
        description="An exception hides a finding. It does not change what the policy checks, and it does not change what a scan would do to anything else."
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              type="submit"
              form="exception-form"
              loading={saving}
              disabled={saving}
            >
              Add exception
            </Button>
          </div>
        }
      >
        <form id="exception-form" onSubmit={save} className="space-y-4">
          {/* The fork, made explicit and made a decision rather than two
              buttons that looked like unrelated features. Which scope you are
              choosing is the most consequential thing on this form, so it is
              the first thing on it and it says what each one costs. */}
          <Field>
            <Label>What should this cover?</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              <ScopeChoice
                selected={!isPattern}
                onSelect={() => setScope("resource")}
                title="One resource"
                detail="Every rule that fails for one named resource is hidden. Nothing else is affected."
              />
              <ScopeChoice
                selected={isPattern}
                onSelect={() => setScope("pattern")}
                title="One rule, for a class"
                detail="One rule stops reporting for every resource of a type in one workspace, including ones created later. Must expire."
                caution
              />
            </div>
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field>
              <Label htmlFor="resource-type">Resource type</Label>
              <Select
                id="resource-type"
                required
                value={draft.resource_type}
                onChange={(e) =>
                  // Clearing the rule matters: the picker is filtered by type,
                  // so keeping it would leave a rule selected that the new type
                  // has no policies for, and the exception would match nothing.
                  setDraft({ ...draft, resource_type: e.target.value, rule_id: "" })
                }
              >
                {resourceTypes.map((type) => (
                  <option key={type.value} value={type.value}>
                    {type.label}
                  </option>
                ))}
              </Select>
            </Field>

            <Field>
              <Label htmlFor="workspace">Workspace</Label>
              <Input
                id="workspace"
                required
                value={draft.workspace}
                onChange={(e) => setDraft({ ...draft, workspace: e.target.value })}
                placeholder="prod-analytics"
              />
            </Field>
          </div>

          {isPattern ? (
            <Field>
              <Label htmlFor="rule">Rule to waive</Label>
              <Select
                id="rule"
                required
                value={draft.rule_id}
                onChange={(e) => setDraft({ ...draft, rule_id: e.target.value })}
              >
                <option value="">Choose a rule</option>
                {rulesForType.map((rule) => (
                  <option key={rule.id} value={rule.id}>
                    {rule.label}
                  </option>
                ))}
              </Select>
              {!rulesForType.length && (
                <p className="text-2xs text-warning">
                  No policies cover {draft.resource_type || "this type"} yet, so
                  there is nothing here to waive.
                </p>
              )}
            </Field>
          ) : (
            <Field>
              <Label htmlFor="resource-id">Resource ID</Label>
              <Input
                id="resource-id"
                required
                value={draft.resource_id}
                onChange={(e) => setDraft({ ...draft, resource_id: e.target.value })}
                placeholder="0123-456789-abcdef"
                className="font-mono"
              />
            </Field>
          )}

          <Field>
            <Label htmlFor="expires">
              Expires {isPattern && <span className="text-danger">(required)</span>}
            </Label>
            <Input
              id="expires"
              type="date"
              required={isPattern}
              value={draft.expires_at}
              onChange={(e) => setDraft({ ...draft, expires_at: e.target.value })}
            />
            <p className="text-2xs text-content-subtle">
              {isPattern
                ? "A class-wide waiver with no end date is a policy change that never went through review. If the rule is wrong, change the rule."
                : "Leave this empty for an exception that never lapses."}
            </p>
          </Field>

          <Field>
            <Label htmlFor="justification">Why</Label>
            <textarea
              id="justification"
              required
              rows={3}
              value={draft.justification}
              onChange={(e) => setDraft({ ...draft, justification: e.target.value })}
              placeholder="Who agreed this, and what makes it acceptable until it expires."
              className="w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-xs text-content placeholder:text-content-subtle focus:border-brand focus:outline-none"
            />
          </Field>
        </form>
      </Dialog>
    </div>
  );
}

function ScopeChoice({
  selected,
  onSelect,
  title,
  detail,
  caution,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  detail: string;
  caution?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "rounded-md border p-3 text-left transition-colors",
        selected
          ? caution
            ? "border-warning bg-warning-subtle"
            : "border-accent bg-accent-subtle"
          : "border-border bg-surface hover:border-border-strong",
      )}
    >
      <span className="flex items-center gap-1.5 text-xs font-medium text-content">
        {caution && selected && (
          <AlertTriangle className="size-3.5 text-warning" aria-hidden />
        )}
        {title}
      </span>
      <span className="mt-1 block text-2xs leading-relaxed text-content-muted">
        {detail}
      </span>
    </button>
  );
}

function ExceptionRow({
  entry,
  impact,
  onRemove,
}: {
  entry: AllowlistEntry;
  impact?: AllowlistImpact;
  onRemove: () => void;
}) {
  const isPattern = entry.match_type === "pattern";
  const expired = entry.expires_at ? new Date(entry.expires_at) < new Date() : false;

  return (
    <TableRow>
      <TableCell className="align-top">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5">
            <Badge variant={isPattern ? "warning" : "outline"}>
              {isPattern ? "class" : "resource"}
            </Badge>
            <Badge variant="outline" className="font-mono">
              {entry.resource_type}
            </Badge>
          </div>
          <span className="break-all font-mono text-2xs text-content">
            {isPattern ? `every ${entry.resource_type}` : entry.resource_id}
          </span>
          {isPattern && (
            <span className="font-mono text-2xs text-content-muted">
              waives {entry.rule_id}
            </span>
          )}
        </div>
      </TableCell>

      <TableCell className="align-top text-xs text-content-muted">
        {entry.workspace}
      </TableCell>

      <TableCell className="align-top text-xs">
        {impact === undefined ? (
          <span className="text-content-subtle">—</span>
        ) : impact.suppressed_findings === 0 ? (
          <span className="text-content-subtle">nothing</span>
        ) : (
          <span className={isPattern ? "text-warning" : "text-content-muted"}>
            {impact.suppressed_findings} finding
            {impact.suppressed_findings === 1 ? "" : "s"}
            {impact.suppressed_resources > 1 &&
              ` across ${impact.suppressed_resources} resources`}
          </span>
        )}
      </TableCell>

      <TableCell className="align-top text-xs">
        {!entry.expires_at ? (
          <span className="text-content-subtle">never</span>
        ) : expired ? (
          <Badge variant="danger">lapsed</Badge>
        ) : (
          <span className="text-content-muted">
            {new Date(entry.expires_at).toLocaleDateString()}
          </span>
        )}
      </TableCell>

      <TableCell className="align-top text-xs text-content-muted">
        <span className="break-words">{entry.justification}</span>
        {entry.created_by && (
          <span className="mt-0.5 block text-2xs text-content-subtle">
            {entry.created_by}
          </span>
        )}
      </TableCell>

      <TableCell className="text-right align-top">
        <Button variant="ghost" size="sm" onClick={onRemove} title="Remove">
          <Trash2 />
        </Button>
      </TableCell>
    </TableRow>
  );
}
