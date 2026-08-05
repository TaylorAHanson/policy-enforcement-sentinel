import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { cn } from "../../lib/utils";

export function Spinner({ className }: { className?: string }) {
  return (
    <Loader2
      className={cn("animate-spin size-4 text-content-subtle", className)}
      aria-label="Loading"
    />
  );
}

/**
 * A placeholder with the shape of the content it stands in for.
 *
 * The dashboard loads a run summary and its findings separately, and swapping
 * a spinner for a table shifts every row on the page. Reserving the space is
 * the difference between "loading" and "jumping".
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded bg-surface-raised",
        "after:absolute after:inset-0 after:-translate-x-full after:animate-[shimmer_1.6s_infinite] after:bg-gradient-to-r after:from-transparent after:via-white/[0.04] after:to-transparent",
        className,
      )}
      aria-hidden
    />
  );
}

export function SkeletonRows({
  rows = 5,
  columns = 4,
}: {
  rows?: number;
  columns?: number;
}) {
  return (
    <div className="divide-y divide-border">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-3 px-3 py-2.5">
          {Array.from({ length: columns }).map((__, c) => (
            <Skeleton
              key={c}
              className={cn("h-3.5", c === 0 ? "w-1/3" : "flex-1")}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-6 py-12 text-center",
        className,
      )}
    >
      {icon && <div className="text-content-subtle mb-1">{icon}</div>}
      <p className="text-sm font-medium text-content">{title}</p>
      {description && (
        <p className="max-w-md text-xs text-content-muted leading-relaxed">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

const ALERT_TONES = {
  info: { cls: "border-info/30 bg-info-subtle text-info", Icon: Info },
  success: {
    cls: "border-success/30 bg-success-subtle text-success",
    Icon: CheckCircle2,
  },
  warning: {
    cls: "border-warning/30 bg-warning-subtle text-warning",
    Icon: AlertTriangle,
  },
  danger: { cls: "border-danger/40 bg-danger-subtle text-danger", Icon: XCircle },
  enforcement: {
    cls: "border-danger/50 bg-danger-subtle text-danger",
    Icon: ShieldAlert,
  },
} as const;

export function Alert({
  tone = "info",
  title,
  children,
  action,
  className,
}: {
  tone?: keyof typeof ALERT_TONES;
  title?: React.ReactNode;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  const { cls, Icon } = ALERT_TONES[tone];
  return (
    <div
      role={tone === "danger" || tone === "enforcement" ? "alert" : "status"}
      className={cn("flex items-start gap-3 rounded-lg border px-4 py-3", cls, className)}
    >
      <Icon className="size-4 shrink-0 mt-0.5" aria-hidden />
      <div className="min-w-0 flex-1">
        {title && <p className="text-[13px] font-semibold">{title}</p>}
        {children && (
          <div className={cn("text-xs leading-relaxed opacity-90", title && "mt-1")}>
            {children}
          </div>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/** Inline error with a retry, for a panel that failed to load. */
export function ErrorState({
  message,
  onRetry,
  className,
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <Alert tone="danger" title="Something went wrong" className={className}>
      <p>{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 underline underline-offset-4 hover:no-underline"
        >
          Try again
        </button>
      )}
    </Alert>
  );
}
