import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "../../lib/utils";

/**
 * Note the `danger` variant, and note that it is visually distinct rather than
 * merely red-tinted. Anything that triggers a Tier 2 or Tier 3 action uses it,
 * and it should never be the default styling for a routine control -- the
 * moment a "Refresh" button looks like a "Delete" button, the colour stops
 * carrying information.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-content-inverse hover:bg-primary-hover shadow-[0_1px_0_0_rgba(0,0,0,0.45)]",
        secondary:
          "bg-surface-raised text-content border border-border-strong hover:bg-surface-overlay",
        ghost: "text-content-muted hover:bg-accent-subtle hover:text-accent",
        outline:
          "border border-border-strong text-content hover:bg-surface-raised",
        danger:
          "bg-danger text-content-inverse hover:brightness-110 shadow-[0_1px_0_0_rgba(0,0,0,0.45)]",
        "danger-outline":
          "border border-danger/50 text-danger hover:bg-danger-subtle",
        link: "text-accent underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-7 px-2.5 text-2xs [&_svg]:size-3.5",
        md: "h-8 px-3 text-[13px] [&_svg]:size-4",
        lg: "h-10 px-4 text-sm [&_svg]:size-4",
        icon: "h-8 w-8 [&_svg]:size-4",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      // A button mid-request must not be clickable again. Relying on the caller
      // to also pass `disabled` makes double submission a matter of discipline.
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Loader2 className="animate-spin" aria-hidden />}
      {children}
    </button>
  ),
);
Button.displayName = "Button";

export { buttonVariants };
