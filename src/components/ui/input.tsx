import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "../../lib/utils";

const fieldBase =
  "w-full rounded-md border border-border-strong bg-surface-raised text-content placeholder:text-content-subtle transition-colors focus-visible:border-accent disabled:opacity-50 disabled:cursor-not-allowed";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }
>(({ className, invalid, ...props }, ref) => (
  <input
    ref={ref}
    aria-invalid={invalid || undefined}
    className={cn(
      fieldBase,
      "h-8 px-2.5 text-[13px]",
      invalid && "border-danger focus-visible:border-danger",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }
>(({ className, invalid, ...props }, ref) => (
  <textarea
    ref={ref}
    aria-invalid={invalid || undefined}
    className={cn(
      fieldBase,
      "min-h-[72px] px-2.5 py-2 text-[13px] leading-relaxed resize-y",
      invalid && "border-danger focus-visible:border-danger",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <div className="relative">
    <select
      ref={ref}
      className={cn(
        fieldBase,
        "h-8 pl-2.5 pr-8 text-[13px] appearance-none cursor-pointer",
        className,
      )}
      {...props}
    >
      {children}
    </select>
    <ChevronDown
      className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 size-3.5 text-content-subtle"
      aria-hidden
    />
  </div>
));
Select.displayName = "Select";

export const Checkbox = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    type="checkbox"
    className={cn(
      "size-3.5 rounded-sm border border-border-strong bg-surface-raised accent-primary cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed",
      className,
    )}
    {...props}
  />
));
Checkbox.displayName = "Checkbox";

export function Label({
  className,
  required,
  children,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement> & { required?: boolean }) {
  return (
    <label
      className={cn("text-xs font-medium text-content-muted", className)}
      {...props}
    >
      {children}
      {required && <span className="text-danger ml-0.5">*</span>}
    </label>
  );
}

/** Label, control, and the description or error that belongs to it. */
export function Field({
  label,
  htmlFor,
  description,
  error,
  required,
  children,
  className,
}: {
  label?: React.ReactNode;
  htmlFor?: string;
  description?: React.ReactNode;
  error?: React.ReactNode;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {label && (
        <Label htmlFor={htmlFor} required={required}>
          {label}
        </Label>
      )}
      {children}
      {error ? (
        <p className="text-2xs text-danger">{error}</p>
      ) : description ? (
        <p className="text-2xs text-content-subtle leading-relaxed">{description}</p>
      ) : null}
    </div>
  );
}
