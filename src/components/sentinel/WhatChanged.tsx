import { useState, type ReactNode } from "react";
import {
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  EyeOff,
  HelpCircle,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";
import type { FindingChanges, TrackedGroup } from "../../services/api";

/**
 * What changed since the previous scan.
 *
 * The dashboard could only ever say what is wrong, and on a real estate that is
 * 3,789 violations of which 3,038 have been identical across every scan and one
 * is new. A four-digit number that has not moved in a month is not information
 * anybody can act on — everything in it looks equally urgent and equally old.
 *
 * So the standing total is demoted to context and the delta leads. The three
 * ways a finding can close are kept apart, because only one of them is somebody
 * having done something: a deleted resource and a narrowed policy both make a
 * finding disappear while leaving the estate exactly as it was, and a dashboard
 * that counts those as remediation is congratulating you for deletions.
 */

const GROUPS: {
  key: keyof Pick<
    FindingChanges,
    "appeared" | "returned" | "fixed" | "resource_gone" | "no_longer_checked" | "unconfirmed"
  >;
  label: (n: number) => string;
  detail: string;
  tone: "danger" | "warning" | "success" | "muted";
  icon: ReactNode;
}[] = [
  {
    key: "appeared",
    label: (n) => `${n} appeared`,
    detail:
      "Not true at the last scan and true now. The shortest list on this page and the only one that is genuinely news.",
    tone: "danger",
    icon: <ArrowUpRight className="size-3.5" />,
  },
  {
    key: "returned",
    label: (n) => `${n} came back`,
    detail:
      "Fixed at some point and broken again. A resource that keeps relapsing is a process problem, and it looks identical to a stable violation if you only count how long it has been open.",
    tone: "warning",
    icon: <RotateCcw className="size-3.5" />,
  },
  {
    key: "fixed",
    label: (n) => `${n} fixed`,
    detail:
      "The rule ran against the resource and passed. The only evidence that means somebody actually did something.",
    tone: "success",
    icon: <CheckCircle2 className="size-3.5" />,
  },
  {
    key: "resource_gone",
    label: (n) => `${n} closed because the resource is gone`,
    detail:
      "The finding is moot because the thing it was about no longer exists. Nothing improved, so this is deliberately not counted as fixed.",
    tone: "muted",
    icon: <Trash2 className="size-3.5" />,
  },
  {
    key: "no_longer_checked",
    label: (n) => `${n} are no longer checked`,
    detail:
      "The resource is still there and a policy stopped asking about it — narrowed, retired, or rescoped. Worth a glance when the number is large, because an edit to one policy file can close hundreds at once.",
    tone: "muted",
    icon: <EyeOff className="size-3.5" />,
  },
  {
    key: "unconfirmed",
    label: (n) => `${n} could not be checked`,
    detail:
      "Still open, and the last few scans were not able to look — usually because discovery could not enumerate that resource type. These are not known to be current, and they are counted apart so that a broken handler cannot pass for a clean estate.",
    tone: "warning",
    icon: <HelpCircle className="size-3.5" />,
  },
];

const TONE: Record<string, string> = {
  danger: "text-danger",
  warning: "text-warning",
  success: "text-success",
  muted: "text-content-muted",
};

export function WhatChanged({ changes }: { changes: FindingChanges }) {
  if (!changes.available) return null;

  const groups = GROUPS.filter((g) => (changes[g.key] as TrackedGroup).count > 0);
  const since = changes.compared_to_at
    ? new Date(changes.compared_to_at).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;

  return (
    <div className="rounded-md border border-border bg-surface-raised/40 p-3">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h2 className="text-xs font-semibold text-content">
          {changes.is_first_scan
            ? "First scan"
            : groups.length
              ? "What changed"
              : "Nothing changed"}
        </h2>
        <span className="text-2xs text-content-muted">
          {changes.is_first_scan ? (
            <>
              Nothing to compare against yet. The next scan will show what moved.
            </>
          ) : (
            <>
              since the scan on {since}. {changes.open.toLocaleString()} findings
              are open in total.
            </>
          )}
        </span>
      </div>

      {!changes.is_first_scan && !groups.length && (
        <p className="text-2xs text-content-muted">
          No finding appeared, closed, or came back. The open list is the same as
          it was last time.
        </p>
      )}

      <div className="space-y-1">
        {groups.map((group) => (
          <ChangeRow
            key={group.key}
            group={changes[group.key] as TrackedGroup}
            label={group.label((changes[group.key] as TrackedGroup).count)}
            detail={group.detail}
            tone={group.tone}
            icon={group.icon}
          />
        ))}
      </div>

      {changes.oldest.count > 0 && <Oldest group={changes.oldest} />}
    </div>
  );
}

function ChangeRow({
  group,
  label,
  detail,
  tone,
  icon,
}: {
  group: TrackedGroup;
  label: string;
  detail: string;
  tone: string;
  icon: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 rounded px-1 py-1 text-left hover:bg-surface-hover"
      >
        <Chevron className="size-3.5 shrink-0 text-content-subtle" />
        <span className={cn("shrink-0", TONE[tone])}>{icon}</span>
        <span className={cn("text-2xs font-medium", TONE[tone])}>{label}</span>
      </button>

      {open && (
        <div className="ml-6 mb-1">
          <p className="mb-1.5 text-2xs leading-relaxed text-content-muted">
            {detail}
          </p>
          <ul className="space-y-0.5">
            {group.items.map((item) => (
              <li key={item.fingerprint} className="text-2xs">
                <code className="font-mono text-content">{item.policy_id}</code>
                <span className="text-content-muted">
                  {" "}
                  &mdash; {item.resource_type}/{item.resource_name}
                  {item.reopened > 0 && ` · came back ${item.reopened}×`}
                </span>
              </li>
            ))}
            {group.count > group.items.length && (
              <li className="text-2xs text-content-subtle">
                and {group.count - group.items.length} more
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * The longest-standing open findings.
 *
 * Age is the one ordering that survives a list this size. Everything here is
 * equally "open"; what separates them is that some have been ignored since the
 * first scan and some arrived this morning.
 */
function Oldest({ group }: { group: TrackedGroup }) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="mt-1 border-t border-border pt-1">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 rounded px-1 py-1 text-left hover:bg-surface-hover"
      >
        <Chevron className="size-3.5 shrink-0 text-content-subtle" />
        <Clock className="size-3.5 shrink-0 text-content-muted" />
        <span className="text-2xs font-medium text-content-muted">
          Open the longest
        </span>
      </button>

      {open && (
        <ul className="ml-6 mb-1 space-y-0.5">
          {group.items.map((item) => (
            <li key={item.fingerprint} className="flex items-baseline gap-2 text-2xs">
              <Badge variant="outline">{item.occurrences} scans</Badge>
              <span>
                <code className="font-mono text-content">{item.policy_id}</code>
                <span className="text-content-muted">
                  {" "}
                  &mdash; {item.resource_type}/{item.resource_name}
                  {item.first_seen_at &&
                    ` · since ${new Date(item.first_seen_at).toLocaleDateString()}`}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
