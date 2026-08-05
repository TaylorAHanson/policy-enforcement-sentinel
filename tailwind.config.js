/** @type {import('tailwindcss').Config} */

// Colours are declared as CSS variables in src/index.css and referenced here by
// semantic name. Two reasons: the branding endpoint overrides `--brand-primary`
// at runtime, which a compiled hex could not support; and naming a colour after
// its job rather than its value means the palette can change in one place.
//
// The tier and severity scales are part of the safety model, not decoration.
// A Tier 3 action is red everywhere it appears because that consistency is what
// makes an unexpected red badge alarming.

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas)",
        surface: {
          DEFAULT: "var(--surface)",
          raised: "var(--surface-raised)",
          overlay: "var(--surface-overlay)",
        },
        border: {
          DEFAULT: "var(--border)",
          strong: "var(--border-strong)",
        },
        content: {
          DEFAULT: "var(--content)",
          muted: "var(--content-muted)",
          subtle: "var(--content-subtle)",
          inverse: "var(--content-inverse)",
        },
        primary: {
          DEFAULT: "var(--brand-primary)",
          hover: "var(--brand-primary-hover)",
          subtle: "var(--brand-primary-subtle)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          subtle: "var(--accent-subtle)",
        },
        success: {
          DEFAULT: "var(--success)",
          subtle: "var(--success-subtle)",
        },
        warning: {
          DEFAULT: "var(--warning)",
          subtle: "var(--warning-subtle)",
        },
        danger: {
          DEFAULT: "var(--danger)",
          subtle: "var(--danger-subtle)",
        },
        info: {
          DEFAULT: "var(--info)",
          subtle: "var(--info-subtle)",
        },
        // The action ladder in app/core/actions.py.
        tier: {
          observe: "var(--tier-observe)",
          "observe-subtle": "var(--tier-observe-subtle)",
          notify: "var(--tier-notify)",
          "notify-subtle": "var(--tier-notify-subtle)",
          restrict: "var(--tier-restrict)",
          "restrict-subtle": "var(--tier-restrict-subtle)",
          destructive: "var(--tier-destructive)",
          "destructive-subtle": "var(--tier-destructive-subtle)",
        },
        severity: {
          critical: "var(--severity-critical)",
          high: "var(--severity-high)",
          medium: "var(--severity-medium)",
          low: "var(--severity-low)",
          none: "var(--severity-none)",
        },
      },
      borderRadius: {
        sm: "0.25rem",
        md: "0.375rem",
        lg: "0.5rem",
        xl: "0.75rem",
      },
      fontSize: {
        // The UI is dense by design: a governance dashboard is read in columns.
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "SF Mono",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 150ms ease-out",
        "slide-up": "slide-up 180ms ease-out",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
