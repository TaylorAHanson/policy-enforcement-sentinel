import * as React from "react";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { cn } from "../../lib/utils";

export function Table({
  className,
  ...props
}: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        className={cn("w-full border-collapse text-[13px]", className)}
        {...props}
      />
    </div>
  );
}

export function TableHead({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn("border-b border-border-strong", className)}
      {...props}
    />
  );
}

export function TableBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("divide-y divide-border", className)} {...props} />;
}

export function TableRow({
  className,
  interactive,
  selected,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement> & {
  interactive?: boolean;
  selected?: boolean;
}) {
  return (
    <tr
      className={cn(
        interactive && "cursor-pointer hover:bg-surface-raised transition-colors",
        selected && "bg-accent-subtle",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({
  className,
  ...props
}: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn("px-3 py-2 align-middle text-content-muted", className)}
      {...props}
    />
  );
}

export function TableHeaderCell({
  className,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-subtle",
        className,
      )}
      {...props}
    />
  );
}

/**
 * A header cell that sorts. Sorting happens on the server, so this only
 * reports intent -- it never reorders a page of rows locally, which would
 * silently sort one page of a paginated result and look like a bug.
 */
export function SortableHeaderCell({
  label,
  field,
  activeField,
  direction,
  onSort,
  className,
}: {
  label: string;
  field: string;
  activeField?: string | null;
  direction?: "asc" | "desc";
  onSort: (field: string) => void;
  className?: string;
}) {
  const active = activeField === field;
  const Icon = !active ? ChevronsUpDown : direction === "asc" ? ArrowUp : ArrowDown;

  return (
    <TableHeaderCell className={cn("p-0", className)}>
      <button
        type="button"
        onClick={() => onSort(field)}
        aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
        className={cn(
          "flex w-full items-center gap-1 px-3 py-2 text-left uppercase tracking-wider transition-colors hover:text-content",
          active && "text-accent",
        )}
      >
        {label}
        <Icon className="size-3 opacity-70" aria-hidden />
      </button>
    </TableHeaderCell>
  );
}
