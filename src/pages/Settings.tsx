import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Bell,
  Bot,
  Braces,
  CalendarClock,
  Check,
  ListOrdered,
  Palette,
  RotateCcw,
  ScanLine,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";
import { Badge } from "../components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import { Checkbox, Input, Select } from "../components/ui/input";
import { ErrorState, Skeleton, Spinner } from "../components/ui/feedback";
import { ConfirmPhraseDialog } from "../components/ui/dialog";
import { TierBadge } from "../components/safety/TierBadge";
import { cn, humanize } from "../lib/utils";
import api from "../services/api";
import type {
  CronPreview,
  SettingDefinition,
  SettingGroup,
} from "../services/api";
import { useSettingsStore } from "../store/settingsStore";

/** The action ladder is a reference card, not a group of editable fields. */
const LADDER_ID = "__action_ladder__";

// Group names come from the backend schema, so an unrecognised one still gets a
// sensible icon rather than a hole in the nav.
const GROUP_ICONS: Record<string, typeof ShieldAlert> = {
  "Enforcement safety": ShieldAlert,
  Scanning: ScanLine,
  Agent: Bot,
  Branding: Palette,
  Notifications: Bell,
};

/**
 * Settings are rendered from the schema the backend publishes, so adding a
 * setting is a one-line change in `settings_store.EDITABLE_FIELDS` rather than
 * a change in two repositories that drift.
 *
 * The danger group is separated, styled differently, and gated behind a typed
 * confirmation. Those four values decide whether the Sentinel is allowed to
 * destroy anything, and they should not sit in a list next to the logo URL.
 */
export default function SettingsPage() {
  const { schema, loading, saving, error, load, update, reset } = useSettingsStore();
  const [pendingDanger, setPendingDanger] = useState<{
    field: SettingDefinition;
    value: unknown;
  } | null>(null);
  // Null until the schema arrives and the first section can be named.
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !schema) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error && !schema) {
    return (
      <div className="mx-auto max-w-3xl">
        <ErrorState message={error} onRetry={() => void load()} />
      </div>
    );
  }

  if (!schema) return null;

  // Safety first in the running order, so the section that decides what the
  // Sentinel may do to real resources is the one you land on.
  const orderedGroups = [
    ...schema.groups.filter((g) => g.danger),
    ...schema.groups.filter((g) => !g.danger),
  ];

  const activeId = active ?? orderedGroups[0]?.name ?? LADDER_ID;
  const activeGroup = orderedGroups.find((g) => g.name === activeId) ?? null;

  const commit = (field: SettingDefinition, value: unknown) => {
    // Turning a danger setting *on* is confirmed; turning it off is not.
    // Making something safer should never require ceremony.
    const escalating =
      field.danger &&
      (field.type === "bool" ? value === true : value !== field.value);

    if (escalating) {
      setPendingDanger({ field, value });
      return;
    }
    void update(field.key, value);
  };

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header>
        <h1 className="text-lg font-semibold text-content">Settings</h1>
        <p className="mt-1 text-xs text-content-muted">
          Values set here are stored in the database and override the deployment's
          environment variables.
        </p>
      </header>

      {/*
        One section at a time rather than anchor links down one long page. With
        five groups stacked, finding the scan concurrency meant scrolling past
        every safety gate — and the settings that matter most were the easiest
        to scroll straight past.
      */}
      <div className="flex flex-col gap-6 md:flex-row md:items-start">
        <SettingsNav
          groups={orderedGroups}
          activeId={activeId}
          onSelect={setActive}
        />

        <div className="min-w-0 flex-1">
          {activeGroup?.danger && (
            <DangerGroup
              group={activeGroup}
              saving={saving}
              onChange={commit}
              onReset={(key) => void reset(key)}
              gates={schema.gates}
            />
          )}

          {activeGroup && !activeGroup.danger && (
            <Card>
              <CardHeader>
                <CardTitle>{activeGroup.name}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-5">
                {activeGroup.fields.map((field) => (
                  <SettingRow
                    key={field.key}
                    field={field}
                    saving={saving === field.key}
                    onChange={(value) => commit(field, value)}
                    onReset={() => void reset(field.key)}
                  />
                ))}
              </CardContent>
            </Card>
          )}

          {activeId === LADDER_ID && (
            <Card>
              <CardHeader>
                <CardTitle>Action ladder</CardTitle>
                <CardDescription>
                  What the Sentinel can do, and what it takes to undo it. Policies
                  request an action; the enforcement gates decide what actually
                  happens.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {schema.action_ladder.map((spec) => (
                  <div
                    key={spec.action}
                    className="flex items-start gap-3 border-b border-border pb-2 last:border-0 last:pb-0"
                  >
                    <TierBadge tier={spec.tier} className="mt-0.5 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <code className="font-mono text-xs text-content">
                          {spec.action}
                        </code>
                        {spec.destructive ? (
                          <Badge variant="danger">irreversible</Badge>
                        ) : spec.undo_method ? (
                          <Badge variant="success">undoable</Badge>
                        ) : null}
                      </div>
                      <p className="mt-0.5 text-2xs leading-relaxed text-content-muted">
                        {spec.description}
                      </p>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <ConfirmPhraseDialog
        open={Boolean(pendingDanger)}
        onClose={() => setPendingDanger(null)}
        onConfirm={() => {
          if (!pendingDanger) return;
          void update(pendingDanger.field.key, pendingDanger.value);
          setPendingDanger(null);
        }}
        title={`Change ${pendingDanger?.field.label ?? "a safety setting"}?`}
        description="This setting controls what the Sentinel is permitted to do to real resources."
        phrase="I understand"
        confirmLabel="Apply the change"
      >
        <p className="text-xs leading-relaxed text-content-muted">
          {pendingDanger?.field.help}
        </p>
      </ConfirmPhraseDialog>
    </div>
  );
}

function SettingsNav({
  groups,
  activeId,
  onSelect,
}: {
  groups: SettingGroup[];
  activeId: string;
  onSelect: (id: string) => void;
}) {
  const items = [
    ...groups.map((group) => ({
      id: group.name,
      label: group.name,
      icon: GROUP_ICONS[group.name] ?? SlidersHorizontal,
      danger: Boolean(group.danger),
      // Surfacing the override count here answers "what has been changed away
      // from the deployment defaults" without opening all five sections.
      overrides: group.fields.filter((f) => f.overridden).length,
    })),
    {
      id: LADDER_ID,
      label: "Action ladder",
      icon: ListOrdered,
      danger: false,
      overrides: 0,
    },
  ];

  return (
    // Horizontal and scrollable on narrow screens, where a 200px column would
    // leave nothing for the settings themselves.
    <nav
      aria-label="Settings sections"
      className="-mx-1 flex shrink-0 gap-1 overflow-x-auto px-1 pb-1 md:sticky md:top-4 md:mx-0 md:w-52 md:flex-col md:overflow-visible md:px-0 md:pb-0"
    >
      {items.map(({ id, label, icon: Icon, danger, overrides }) => {
        const isActive = id === activeId;
        return (
          <button
            key={id}
            type="button"
            onClick={() => onSelect(id)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-left text-[13px] font-medium transition-colors md:w-full",
              isActive
                ? danger
                  ? "bg-danger-subtle text-danger"
                  : "bg-accent-subtle text-accent"
                : danger
                  ? // No opacity modifier: the palette tokens are raw
                    // `var(--x)` without an `<alpha-value>`, so `text-danger/80`
                    // silently produces no colour at all.
                    "text-danger hover:bg-danger-subtle"
                  : "text-content hover:bg-accent-subtle hover:text-accent",
            )}
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            <span className="flex-1 whitespace-nowrap md:whitespace-normal">
              {label}
            </span>
            {overrides > 0 && (
              <span
                className="shrink-0 rounded-full bg-surface-raised px-1.5 py-0.5 font-mono text-2xs text-content-subtle"
                title={`${overrides} setting(s) overridden in this section`}
              >
                {overrides}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}

function DangerGroup({
  group,
  saving,
  onChange,
  onReset,
  gates,
}: {
  group: SettingGroup;
  saving: string | null;
  onChange: (field: SettingDefinition, value: unknown) => void;
  onReset: (key: string) => void;
  gates: Array<{ gate: string; description: string }>;
}) {
  // The gates describe what it takes for a destructive action to go ahead, so
  // they belong to the group holding the enforcement switch. Other groups are
  // marked dangerous for their own reasons — Scanning contains the scheduled
  // run mode — and printing the gate list above their fields described a
  // mechanism those settings have nothing to do with.
  const ownsGates = group.fields.some((f) => f.key === "ENFORCEMENT_ENABLED");

  return (
    <Card tone="danger">
      <CardHeader className="border-danger/30">
        <CardTitle className="flex items-center gap-2 text-danger">
          <ShieldAlert className="size-4" aria-hidden />
          {group.name}
        </CardTitle>
        <CardDescription>
          {ownsGates
            ? "Destruction requires all five gates below to agree. Any one of them refusing is enough to downgrade an action to a warning."
            : "These settings change what the Sentinel is permitted to do to real resources. Each one takes a typed confirmation."}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        {ownsGates && (
          <ol className="space-y-1.5 rounded-md border border-border bg-surface-raised px-4 py-3">
            {gates.map((gate, index) => (
              <li key={gate.gate} className="flex gap-2 text-2xs leading-relaxed">
                <span className="shrink-0 font-mono text-content-subtle">
                  {index + 1}.
                </span>
                <span className="text-content-muted">
                  <span className="font-medium text-content">
                    {humanize(gate.gate)}
                  </span>{" "}
                  — {gate.description}
                </span>
              </li>
            ))}
          </ol>
        )}

        {group.fields.map((field) => (
          <SettingRow
            key={field.key}
            field={field}
            saving={saving === field.key}
            onChange={(value) => onChange(field, value)}
            onReset={() => onReset(field.key)}
          />
        ))}
      </CardContent>
    </Card>
  );
}

const CRON_EXAMPLES: Array<{ expression: string; label: string }> = [
  { expression: "0 2 * * *", label: "Daily at 02:00" },
  { expression: "0 2 * * 1", label: "Mondays at 02:00" },
  { expression: "0 */6 * * *", label: "Every 6 hours" },
];

/**
 * A cron expression with a live answer to "so when does it actually run?".
 *
 * The schedule is the one setting whose effect stays invisible for hours after
 * saving it, and `0 2 * * *` versus `2 0 * * *` is a twenty-two hour mistake
 * that looks identical on the page. The backend resolves the expression so the
 * preview cannot disagree with the worker about what it means.
 */
function CronControl({
  value,
  disabled,
  onDraftChange,
  onCommit,
}: {
  value: string;
  disabled: boolean;
  onDraftChange: (value: string) => void;
  onCommit: () => void;
}) {
  const [preview, setPreview] = useState<CronPreview | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Debounced: this fires per keystroke otherwise, and a half-typed
    // expression is invalid in ways not worth reporting.
    const timer = setTimeout(() => {
      api.settings
        .cronPreview(value)
        .then((result) => {
          if (!cancelled) setPreview(result);
        })
        .catch(() => {
          if (!cancelled) setPreview(null);
        });
    }, 300);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [value]);

  return (
    <div className="space-y-2">
      <Input
        value={value}
        disabled={disabled}
        placeholder="0 2 * * *"
        spellCheck={false}
        className="max-w-[200px] font-mono"
        onChange={(e) => onDraftChange(e.target.value)}
        onBlur={onCommit}
      />

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-2xs text-content-subtle">Examples:</span>
        {CRON_EXAMPLES.map((example) => (
          <button
            key={example.expression}
            type="button"
            disabled={disabled}
            onClick={() => onDraftChange(example.expression)}
            className="rounded border border-border px-1.5 py-0.5 font-mono text-2xs text-content-muted transition-colors hover:border-border-strong hover:text-content"
            title={example.label}
          >
            {example.expression}
          </button>
        ))}
      </div>

      {preview && !preview.valid && (
        <p className="flex items-start gap-1.5 text-2xs text-danger">
          <AlertTriangle className="mt-0.5 size-3 shrink-0" aria-hidden />
          {preview.error}
        </p>
      )}

      {preview?.valid && preview.disabled && (
        <p className="text-2xs text-content-subtle">
          Blank — scheduled scanning is off. Unattended scans will not run.
        </p>
      )}

      {preview?.valid && !preview.disabled && (
        <div className="flex items-start gap-1.5 text-2xs text-content-muted">
          <CalendarClock className="mt-0.5 size-3 shrink-0" aria-hidden />
          <span>
            Next runs (UTC):{" "}
            {preview.next_runs.map((run) => formatRun(run)).join(", ")}
          </span>
        </div>
      )}
    </div>
  );
}

function formatRun(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    hour12: false,
  });
}

function SettingRow({
  field,
  saving,
  onChange,
  onReset,
}: {
  field: SettingDefinition;
  saving: boolean;
  onChange: (value: unknown) => void;
  onReset: () => void;
}) {
  // Text inputs are held locally and committed on blur. Saving on every
  // keystroke would fire a request per character and, for a comma-separated
  // workspace list, briefly persist half a workspace name.
  const [draft, setDraft] = useState(String(field.value ?? ""));

  // Re-seed the draft when the stored value changes underneath it — a reset to
  // default, or another admin's edit arriving with a reload. Adjusting during
  // render rather than in an effect means the input never paints one frame
  // showing the old value.
  const [lastValue, setLastValue] = useState(field.value);
  if (field.value !== lastValue) {
    setLastValue(field.value);
    setDraft(String(field.value ?? ""));
  }

  const control = () => {
    switch (field.type) {
      case "bool":
        return (
          <label className="flex items-center gap-2">
            <Checkbox
              checked={Boolean(field.value)}
              disabled={saving}
              onChange={(e) => onChange(e.target.checked)}
            />
            <span className="text-xs text-content-muted">
              {field.value ? "Enabled" : "Disabled"}
            </span>
          </label>
        );

      case "select":
        return (
          <Select
            value={String(field.value ?? "")}
            disabled={saving}
            onChange={(e) => onChange(e.target.value)}
            className="max-w-xs"
          >
            {(field.options ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </Select>
        );

      case "int":
        return (
          <Input
            type="number"
            value={draft}
            disabled={saving}
            className="max-w-[140px]"
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => {
              const parsed = Number(draft);
              if (Number.isFinite(parsed) && parsed !== field.value) onChange(parsed);
            }}
          />
        );

      case "cron":
        return (
          <CronControl
            value={draft}
            disabled={saving}
            onDraftChange={setDraft}
            onCommit={() => draft !== field.value && onChange(draft)}
          />
        );

      case "color":
        return (
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={draft || "#000000"}
              disabled={saving}
              onChange={(e) => {
                setDraft(e.target.value);
                onChange(e.target.value);
              }}
              className="h-8 w-12 cursor-pointer rounded border border-border-strong bg-surface-raised"
            />
            <Input
              value={draft}
              disabled={saving}
              className="max-w-[120px] font-mono"
              onChange={(e) => setDraft(e.target.value)}
              onBlur={() => draft !== field.value && onChange(draft)}
            />
          </div>
        );

      default:
        return (
          <Input
            value={draft}
            disabled={saving}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => draft !== field.value && onChange(draft)}
          />
        );
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-content">{field.label}</span>
        <SettingKey settingKey={field.key} />
        {field.danger && <Badge variant="danger">safety</Badge>}
        {field.overridden && (
          <>
            <Badge variant="info">overridden</Badge>
            <button
              type="button"
              onClick={onReset}
              className="inline-flex items-center gap-1 text-2xs text-content-subtle transition-colors hover:text-content"
              title="Drop the override and fall back to the deployment default"
            >
              <RotateCcw className="size-3" aria-hidden />
              reset
            </button>
          </>
        )}
        {saving && <Spinner className="size-3" />}
      </div>

      {control()}

      {field.help && (
        <p className="text-2xs leading-relaxed text-content-subtle">{field.help}</p>
      )}
    </div>
  );
}

/**
 * The underlying environment variable, behind an icon.
 *
 * It used to sit at the foot of each row in the same colour as the help text,
 * one gap above the next setting's label — so it read as a heading for the
 * setting below it rather than a footnote on the one above. It is still worth
 * having, since it is the name you need when writing .env or databricks.yml,
 * so it moved next to the label it actually belongs to.
 */
function SettingKey({ settingKey }: { settingKey: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(settingKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard access needs a secure context, which rules it out on some
      // plain-http deployments. The name is in the tooltip either way, so
      // there is nothing worth interrupting anyone about.
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      title={copied ? "Copied" : `${settingKey} — click to copy`}
      aria-label={`Environment variable ${settingKey}, click to copy`}
      className="inline-flex shrink-0 items-center rounded p-0.5 text-content-subtle transition-colors hover:bg-surface-raised hover:text-content"
    >
      {copied ? (
        <Check className="size-3" aria-hidden />
      ) : (
        <Braces className="size-3" aria-hidden />
      )}
    </button>
  );
}
