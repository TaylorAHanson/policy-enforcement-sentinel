import { Search, X } from "lucide-react";
import { Button } from "../ui/button";
import { Checkbox, Input, Select } from "../ui/input";
import { humanize } from "../../lib/utils";
import type { Facets, FindingFilters } from "../../services/api";

/**
 * Filters built from the run's own facet counts.
 *
 * The options come from the server's `GROUP BY` over this run's findings, so
 * the dropdowns only ever offer values that exist. A static list of every
 * resource type the product supports leads operators to select one that
 * matches nothing and conclude the scan is broken.
 */
export function FacetFilters({
  facets,
  filters,
  onChange,
  onReset,
  disabled,
}: {
  facets: Facets | null;
  filters: FindingFilters;
  onChange: <K extends keyof FindingFilters>(key: K, value: FindingFilters[K]) => void;
  onReset: () => void;
  disabled?: boolean;
}) {
  const hasFilters =
    Boolean(filters.severity) ||
    Boolean(filters.category) ||
    Boolean(filters.resource_type) ||
    Boolean(filters.effective_action) ||
    Boolean(filters.search) ||
    Boolean(filters.downgraded_only) ||
    filters.kind !== "violation";

  const facetSelect = (
    key: keyof FindingFilters,
    label: string,
    values: Facets[keyof Facets] | undefined,
  ) => (
    <Select
      aria-label={label}
      value={(filters[key] as string) ?? ""}
      disabled={disabled || !values?.length}
      onChange={(e) => onChange(key, (e.target.value || undefined) as never)}
      className="w-[168px]"
    >
      <option value="">{label}: any</option>
      {values?.map(({ value, count }) => (
        <option key={value} value={value}>
          {humanize(value)} ({count})
        </option>
      ))}
    </Select>
  );

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2.5">
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-content-subtle"
          aria-hidden
        />
        <Input
          value={filters.search ?? ""}
          onChange={(e) => onChange("search", e.target.value || undefined)}
          placeholder="Search resources and messages"
          disabled={disabled}
          className="w-[260px] pl-7"
        />
      </div>

      <Select
        aria-label="Result kind"
        value={filters.kind ?? ""}
        disabled={disabled}
        onChange={(e) => onChange("kind", e.target.value || undefined)}
        className="w-[150px]"
      >
        <option value="violation">Violations</option>
        <option value="check">Passing checks</option>
        <option value="">All results</option>
      </Select>

      {facetSelect("severity", "Severity", facets?.severity)}
      {facetSelect("category", "Category", facets?.category)}
      {facetSelect("resource_type", "Resource", facets?.resource_type)}
      {facetSelect("effective_action", "Action", facets?.effective_action)}

      <label className="flex items-center gap-1.5 text-xs text-content-muted">
        <Checkbox
          checked={Boolean(filters.downgraded_only)}
          disabled={disabled}
          onChange={(e) => onChange("downgraded_only", e.target.checked || undefined)}
        />
        Downgraded only
      </label>

      {hasFilters && (
        <Button variant="ghost" size="sm" onClick={onReset} disabled={disabled}>
          <X />
          Clear
        </Button>
      )}
    </div>
  );
}
