import { ArrowDown, Eye, Bell, Lock, Trash2 } from "lucide-react";
import { Badge, type BadgeProps } from "../ui/badge";
import { cn } from "../../lib/utils";
import { TIER_LABELS } from "../../services/api";

/**
 * The visual half of the action ladder.
 *
 * Tier is shown everywhere an action is shown. An operator scanning a table of
 * two hundred findings needs to see at a glance which ones would change
 * something, and the tier is the only field that answers that — the action
 * name alone requires knowing that QUARANTINE is reversible and TERMINATE is
 * not.
 */

const TIER_ICONS = [Eye, Bell, Lock, Trash2] as const;

const TIER_VARIANTS: BadgeProps["variant"][] = [
  "tier-0",
  "tier-1",
  "tier-2",
  "tier-3",
];

export function TierBadge({
  tier,
  showLabel = true,
  size = "sm",
  className,
}: {
  tier: number | null | undefined;
  showLabel?: boolean;
  size?: BadgeProps["size"];
  className?: string;
}) {
  // An unknown tier renders as Observe rather than as nothing. A blank cell
  // reads as "harmless"; this reads as "recorded only", which is what an
  // unresolved action actually is.
  const level = tier == null || tier < 0 || tier > 3 ? 0 : tier;
  const Icon = TIER_ICONS[level];

  return (
    <Badge variant={TIER_VARIANTS[level]} size={size} className={className}>
      <Icon aria-hidden />
      {showLabel ? TIER_LABELS[level] : `T${level}`}
    </Badge>
  );
}

/**
 * What was asked for, what will actually happen, and why they differ.
 *
 * Showing only the effective action hides the fact that a policy asked for
 * something stronger and a gate refused — which is exactly the information
 * somebody needs when they are wondering why enforcement "did nothing".
 */
export function ActionCell({
  requestedAction,
  effectiveAction,
  tier,
  requestedTier,
  downgradeReason,
  executed,
  className,
}: {
  requestedAction?: string | null;
  effectiveAction?: string | null;
  tier?: number | null;
  requestedTier?: number | null;
  downgradeReason?: string | null;
  executed?: boolean;
  className?: string;
}) {
  if (!requestedAction && !effectiveAction) {
    return <span className="text-content-subtle">—</span>;
  }

  const downgraded =
    Boolean(requestedAction) &&
    Boolean(effectiveAction) &&
    requestedAction !== effectiveAction;

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div className="flex items-center gap-1.5">
        {downgraded && (
          <>
            <span className="font-mono text-2xs text-content-subtle line-through">
              {requestedAction}
            </span>
            <ArrowDown className="size-3 shrink-0 text-content-subtle" aria-hidden />
          </>
        )}
        <span className="font-mono text-xs text-content">
          {effectiveAction ?? requestedAction}
        </span>
        <TierBadge tier={tier ?? requestedTier} showLabel={false} />
        {executed && (
          <Badge variant="success" size="sm">
            done
          </Badge>
        )}
      </div>
      {downgraded && downgradeReason && (
        <p className="text-2xs leading-snug text-content-subtle" title={downgradeReason}>
          {downgradeReason}
        </p>
      )}
    </div>
  );
}

/** Compact legend, shown above tables and in the preflight dialog. */
export function TierLegend({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1.5", className)}>
      {[0, 1, 2, 3].map((tier) => (
        <div key={tier} className="flex items-center gap-1.5">
          <TierBadge tier={tier} />
          <span className="text-2xs text-content-subtle">
            {
              [
                "records only",
                "emails the owner",
                "reversible, undo stored",
                "irreversible",
              ][tier]
            }
          </span>
        </div>
      ))}
    </div>
  );
}
