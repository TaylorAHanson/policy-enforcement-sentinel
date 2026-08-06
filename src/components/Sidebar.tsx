import { NavLink } from "react-router-dom";
import {
  BookOpen,
  Code,
  ExternalLink,
  FlaskConical,
  MonitorPlay,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { cn } from "../lib/utils";
import type { Branding } from "../services/api";

const REPO_URL =
  "https://github.com/databricks-field-eng/policy-enforcement-sentinel";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Shield;
  end?: boolean;
}

const PRIMARY_NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Shield, end: true },
  { to: "/policies", label: "Policies", icon: Code },
  { to: "/allowlist", label: "Allowlist", icon: ShieldCheck },
  { to: "/testing", label: "Testing Center", icon: FlaskConical },
  { to: "/settings", label: "Settings", icon: Settings },
];

const SECONDARY_NAV: NavItem[] = [
  { to: "/reference", label: "Quick Reference", icon: BookOpen },
  { to: "/releases", label: "Release Notes", icon: Sparkles },
  { to: "/presentation", label: "Presentation", icon: MonitorPlay },
];

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
    isActive
      ? "bg-accent-subtle text-accent"
      : "text-content hover:bg-accent-subtle hover:text-accent",
  );

export function Sidebar({
  branding,
  unreadReleases,
}: {
  branding: Branding;
  unreadReleases?: boolean;
}) {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex h-16 shrink-0 items-center gap-2.5 border-b border-border px-5">
        {branding.logo_url ? (
          <img
            src={branding.logo_url}
            alt=""
            // The logo is supplied by the operator and may be any colour; the
            // sidebar is always dark, so it is normalised to white.
            className="h-7 max-w-[80px] shrink-0 object-contain brightness-0 invert"
          />
        ) : (
          <Shield className="size-5 shrink-0 text-primary" aria-hidden />
        )}
        <span
          className="line-clamp-2 text-[13px] font-semibold leading-tight text-content"
          title={branding.name}
        >
          {branding.name || "Sentinel"}
        </span>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
        {PRIMARY_NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={linkClass}>
            <Icon className="size-4 shrink-0" aria-hidden />
            {label}
          </NavLink>
        ))}

        <div className="px-3 pb-2 pt-5 text-2xs font-semibold uppercase tracking-wider text-content-subtle">
          Extras
        </div>

        {SECONDARY_NAV.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={linkClass}>
            <Icon className="size-4 shrink-0" aria-hidden />
            <span className="flex-1">{label}</span>
            {to === "/releases" && unreadReleases && (
              <span
                className="size-1.5 rounded-full bg-accent"
                aria-label="New release notes"
              />
            )}
          </NavLink>
        ))}

        <a
          href={REPO_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium text-content transition-colors hover:bg-accent-subtle hover:text-accent"
        >
          <Code className="size-4 shrink-0" aria-hidden />
          <span className="flex-1">GitHub Repo</span>
          <ExternalLink className="size-3 opacity-50" aria-hidden />
        </a>
      </nav>
    </aside>
  );
}
