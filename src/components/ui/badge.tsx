import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded font-medium whitespace-nowrap border",
  {
    variants: {
      variant: {
        neutral: "bg-surface-raised text-content-muted border-border-strong",
        info: "bg-info-subtle text-info border-info/30",
        success: "bg-success-subtle text-success border-success/30",
        warning: "bg-warning-subtle text-warning border-warning/30",
        danger: "bg-danger-subtle text-danger border-danger/30",
        outline: "bg-transparent text-content-muted border-border-strong",
        // One per rung of the ladder in app/core/actions.py.
        "tier-0": "bg-tier-observe-subtle text-tier-observe border-tier-observe/30",
        "tier-1": "bg-tier-notify-subtle text-tier-notify border-tier-notify/30",
        "tier-2": "bg-tier-restrict-subtle text-tier-restrict border-tier-restrict/40",
        "tier-3":
          "bg-tier-destructive-subtle text-tier-destructive border-tier-destructive/50",
      },
      size: {
        sm: "px-1.5 py-0 text-2xs [&_svg]:size-3",
        md: "px-2 py-0.5 text-xs [&_svg]:size-3.5",
      },
    },
    defaultVariants: { variant: "neutral", size: "sm" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, size, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, size }), className)} {...props} />
  );
}

const SEVERITY_VARIANT: Record<string, BadgeProps["variant"]> = {
  CRITICAL: "danger",
  HIGH: "warning",
  MEDIUM: "warning",
  LOW: "neutral",
  NONE: "outline",
};

export function SeverityBadge({
  severity,
  size = "sm",
  className,
}: {
  severity?: string | null;
  size?: BadgeProps["size"];
  className?: string;
}) {
  const key = (severity || "NONE").toUpperCase();
  return (
    <Badge
      variant={SEVERITY_VARIANT[key] ?? "neutral"}
      size={size}
      className={cn(
        // HIGH and MEDIUM share the warning variant but are not the same thing.
        key === "HIGH" && "text-severity-high border-severity-high/40",
        className,
      )}
    >
      {key}
    </Badge>
  );
}

export { badgeVariants };
