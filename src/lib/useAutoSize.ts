import { useLayoutEffect, type RefObject } from "react";

/**
 * Grows a textarea to fit its content, up to a fraction of a container.
 *
 * A fixed-height input wastes most of the pane on a three-line payload and
 * forces scrolling inside a scrollbox on a large one — and the thing you want
 * to read while editing input is usually the result underneath it. Sizing to
 * the content gives the leftover space to the result by default, and caps the
 * input so a big payload can never push the result off screen entirely.
 *
 * Runs in a layout effect so the height is set before paint; measuring after
 * paint makes the box visibly jump on every keystroke.
 */
export function useAutoSize(
  ref: RefObject<HTMLTextAreaElement | null>,
  value: string,
  {
    containerRef,
    maxFraction = 0.5,
    minHeight = 96,
  }: {
    containerRef?: RefObject<HTMLElement | null>;
    maxFraction?: number;
    minHeight?: number;
  } = {},
) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    const resize = () => {
      const container = containerRef?.current;
      // Without a container to measure against, fall back to the viewport
      // rather than growing without limit.
      const available = container?.clientHeight || window.innerHeight;
      const max = Math.max(minHeight, available * maxFraction);

      // Collapse first: scrollHeight only shrinks back if the element is not
      // already holding the taller height.
      el.style.height = "auto";
      const next = Math.min(Math.max(el.scrollHeight, minHeight), max);
      el.style.height = `${next}px`;
      // Only scroll once the cap is actually reached, so there is no
      // permanently visible scrollbar on a short payload.
      el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
    };

    resize();

    // The pane changes height when the window resizes or the surrounding
    // layout reflows, and the cap is a fraction of it.
    const container = containerRef?.current;
    if (!container || typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(resize);
    observer.observe(container);
    return () => observer.disconnect();
  }, [ref, value, containerRef, maxFraction, minHeight]);
}
