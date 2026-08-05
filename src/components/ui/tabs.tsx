import * as React from "react";
import { cn } from "../../lib/utils";

export interface TabItem {
  id: string;
  label: React.ReactNode;
  count?: number;
  disabled?: boolean;
}

export function Tabs({
  items,
  value,
  onChange,
  className,
}: {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={cn("flex items-center gap-1 border-b border-border", className)}
    >
      {items.map((item) => {
        const active = item.id === value;
        return (
          <button
            key={item.id}
            role="tab"
            type="button"
            aria-selected={active}
            disabled={item.disabled}
            onClick={() => onChange(item.id)}
            className={cn(
              "relative flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
              active
                ? "text-accent"
                : "text-content-muted hover:text-content",
            )}
          >
            {item.label}
            {item.count != null && (
              <span
                className={cn(
                  "rounded px-1 py-0.5 text-2xs tabular-nums",
                  active
                    ? "bg-accent-subtle text-accent"
                    : "bg-surface-raised text-content-subtle",
                )}
              >
                {item.count}
              </span>
            )}
            {active && (
              <span className="absolute inset-x-0 -bottom-px h-px bg-accent" />
            )}
          </button>
        );
      })}
    </div>
  );
}
