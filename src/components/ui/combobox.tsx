import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { cn } from "../../lib/utils";

export interface ComboboxOption {
  value: string;
  label: string;
  /** Second line, for anything that helps tell two similar options apart. */
  description?: string;
  /** Rendered on the right of the row and of the closed button. */
  badge?: React.ReactNode;
  /** Extra text that should match a search but is not displayed. */
  keywords?: string;
}

/**
 * A searchable single-select.
 *
 * Written rather than pulled in because the two libraries that do this well
 * both bring a popover primitive with them, and this needs to match the
 * existing inputs more than it needs to be general.
 *
 * Filtering is a plain substring match over label, description and keywords.
 * Fuzzy matching sounds better than it reads: with a list of policy filenames,
 * it mostly produces confident matches on things you did not mean.
 */
export function Combobox({
  options,
  value,
  onChange,
  placeholder = "Select…",
  searchPlaceholder = "Search…",
  emptyMessage = "Nothing matches.",
  disabled,
  className,
  buttonClassName,
}: {
  options: ComboboxOption[];
  value?: string | null;
  onChange: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  disabled?: boolean;
  className?: string;
  buttonClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const selected = options.find((o) => o.value === value) ?? null;

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((o) =>
      `${o.label} ${o.description ?? ""} ${o.keywords ?? ""}`
        .toLowerCase()
        .includes(needle),
    );
  }, [options, query]);

  // Closing on an outside click rather than on blur: blur fires before the
  // click that caused it lands on an option, so selecting with the mouse would
  // close the list first and select nothing.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const show = () => {
    if (disabled) return;
    setOpen(true);
    setQuery("");
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const choose = (option: ComboboxOption) => {
    onChange(option.value);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => {
        const next = e.key === "ArrowDown" ? i + 1 : i - 1;
        const wrapped = (next + matches.length) % Math.max(1, matches.length);
        const rows = listRef.current?.querySelectorAll("[data-option]");
        rows?.[wrapped]?.scrollIntoView({ block: "nearest" });
        return wrapped;
      });
      return;
    }
    if (e.key === "Enter" && matches[active]) {
      e.preventDefault();
      choose(matches[active]);
    }
  };

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          "flex h-8 w-full items-center gap-2 rounded-md border border-border-strong bg-surface-raised px-2.5 text-left text-[13px] text-content transition-colors",
          "hover:border-accent/60 focus:border-accent focus:outline-none disabled:opacity-50",
          buttonClassName,
        )}
      >
        <span
          className={cn(
            "min-w-0 flex-1 truncate",
            !selected && "text-content-subtle",
          )}
        >
          {selected?.label ?? placeholder}
        </span>
        {selected?.badge}
        <ChevronsUpDown className="size-3.5 shrink-0 text-content-subtle" aria-hidden />
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-md border border-border-strong bg-surface shadow-lg">
          <div className="flex items-center gap-2 border-b border-border px-2.5">
            <Search className="size-3.5 shrink-0 text-content-subtle" aria-hidden />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              placeholder={searchPlaceholder}
              className="h-8 w-full bg-transparent text-[13px] text-content placeholder:text-content-subtle focus:outline-none"
            />
          </div>

          <div ref={listRef} role="listbox" className="max-h-72 overflow-y-auto p-1">
            {!matches.length ? (
              <p className="px-2 py-3 text-center text-2xs text-content-subtle">
                {emptyMessage}
              </p>
            ) : (
              matches.map((option, i) => {
                const isSelected = option.value === value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    data-option
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => choose(option)}
                    onMouseEnter={() => setActive(i)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-2xs transition-colors",
                      i === active
                        ? "bg-accent-subtle text-accent"
                        : "text-content-muted",
                    )}
                  >
                    <Check
                      className={cn(
                        "size-3 shrink-0",
                        isSelected ? "opacity-100" : "opacity-0",
                      )}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{option.label}</span>
                      {option.description && (
                        <span className="block truncate text-content-subtle">
                          {option.description}
                        </span>
                      )}
                    </span>
                    {option.badge}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
