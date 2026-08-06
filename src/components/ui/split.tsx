import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "../../lib/utils";

/**
 * A two-pane horizontal split with a draggable divider.
 *
 * The ratio is the *left* pane's share of the width, clamped so neither side
 * can be dragged to nothing — a pane collapsed to zero looks like a bug and
 * there is no obvious way back from it. Use the collapse control that owns the
 * pane for that instead.
 *
 * The value is reported on every frame of the drag so the caller can persist
 * it, but the drag itself is tracked in a ref rather than state: re-rendering
 * a Monaco instance on every mousemove is visibly slow.
 */
export function SplitPane({
  left,
  right,
  ratio,
  onRatioChange,
  min = 0.2,
  max = 0.8,
  className,
}: {
  left: React.ReactNode;
  right: React.ReactNode;
  ratio: number;
  onRatioChange: (ratio: number) => void;
  min?: number;
  max?: number;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  const clamp = useCallback(
    (value: number) => Math.min(max, Math.max(min, value)),
    [min, max],
  );

  useEffect(() => {
    if (!dragging) return;

    const move = (e: MouseEvent) => {
      const box = containerRef.current?.getBoundingClientRect();
      if (!box || box.width === 0) return;
      onRatioChange(clamp((e.clientX - box.left) / box.width));
    };

    const stop = () => setDragging(false);

    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
    // Without this the drag paints a text selection across both panes.
    const previousSelect = document.body.style.userSelect;
    const previousCursor = document.body.style.cursor;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";

    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
      document.body.style.userSelect = previousSelect;
      document.body.style.cursor = previousCursor;
    };
  }, [dragging, clamp, onRatioChange]);

  const nudge = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    onRatioChange(clamp(ratio + (e.key === "ArrowLeft" ? -0.02 : 0.02)));
  };

  const percent = clamp(ratio) * 100;

  return (
    <div ref={containerRef} className={cn("flex min-h-0 min-w-0", className)}>
      <div className="flex min-h-0 min-w-0" style={{ width: `${percent}%` }}>
        {left}
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={Math.round(min * 100)}
        aria-valuemax={Math.round(max * 100)}
        tabIndex={0}
        onMouseDown={() => setDragging(true)}
        onDoubleClick={() => onRatioChange(0.5)}
        onKeyDown={nudge}
        title="Drag to resize, double-click to even them up"
        className={cn(
          // A 9px hit area around a 1px line. A divider only as wide as it
          // looks is genuinely hard to grab.
          "group relative mx-1 w-2 shrink-0 cursor-col-resize focus:outline-none",
        )}
      >
        <span
          className={cn(
            "absolute inset-y-0 left-1/2 w-px -translate-x-1/2 rounded transition-colors",
            dragging
              ? "bg-accent"
              : "bg-border group-hover:bg-accent group-focus:bg-accent",
          )}
        />
      </div>

      <div className="flex min-h-0 min-w-0 flex-1">{right}</div>
    </div>
  );
}
