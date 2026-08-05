import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn, formatNumber } from "../../lib/utils";
import { Button } from "./button";
import { Select } from "./input";

/**
 * Offset pagination controls for a server-paginated list.
 *
 * `total` is what the server reported, not the length of the current page.
 * The distinction matters: showing "1-50 of 50" when there are thousands of
 * findings is how a dashboard quietly hides most of a scan.
 */
export function Pagination({
  offset,
  limit,
  total,
  onOffsetChange,
  onLimitChange,
  pageSizes = [25, 50, 100, 250],
  className,
  busy,
}: {
  offset: number;
  limit: number;
  total: number;
  onOffsetChange: (offset: number) => void;
  onLimitChange?: (limit: number) => void;
  pageSizes?: number[];
  className?: string;
  busy?: boolean;
}) {
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);
  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4 border-t border-border px-3 py-2",
        className,
      )}
    >
      <p className="text-2xs text-content-subtle tabular-nums">
        {total === 0
          ? "No results"
          : `${formatNumber(first)}–${formatNumber(last)} of ${formatNumber(total)}`}
      </p>

      <div className="flex items-center gap-2">
        {onLimitChange && (
          <Select
            value={limit}
            onChange={(e) => {
              // Changing page size from deep in a list would otherwise land on
              // an arbitrary offset; going back to the first page is the only
              // predictable behaviour.
              onLimitChange(Number(e.target.value));
              onOffsetChange(0);
            }}
            className="h-7 w-[72px] text-2xs"
            aria-label="Results per page"
          >
            {pageSizes.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </Select>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          disabled={!canPrev || busy}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          aria-label="Previous page"
        >
          <ChevronLeft />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          disabled={!canNext || busy}
          onClick={() => onOffsetChange(offset + limit)}
          aria-label="Next page"
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}
