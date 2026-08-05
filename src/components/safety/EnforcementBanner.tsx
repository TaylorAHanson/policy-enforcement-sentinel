import { ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { useSettingsStore } from "../../store/settingsStore";

/**
 * A persistent, unmissable strip shown whenever enforcement is switched on.
 *
 * Enforcement being enabled is the difference between a tool that writes
 * reports and one that deletes production resources, and that state is
 * otherwise invisible from every page except Settings. It stays until somebody
 * turns enforcement off — deliberately not dismissible, because the risk it
 * describes does not go away when you stop looking at it.
 */
export function EnforcementBanner() {
  const enabled = useSettingsStore((s) => s.enforcementEnabled());
  const workspaces = useSettingsStore((s) => s.destructiveWorkspaces());

  if (!enabled) return null;

  return (
    <div
      role="alert"
      className="flex shrink-0 items-center gap-3 border-b border-danger/40 bg-danger-subtle px-8 py-2 text-danger"
    >
      <ShieldAlert className="size-4 shrink-0" aria-hidden />
      <p className="flex-1 text-xs">
        <span className="font-semibold">Enforcement is enabled.</span>{" "}
        {workspaces.length ? (
          <>
            Destructive actions are permitted in{" "}
            <span className="font-mono">{workspaces.join(", ")}</span>, subject to
            per-run approval.
          </>
        ) : (
          <>
            No workspaces are listed for destructive actions, so Tier 3 actions
            will still be downgraded.
          </>
        )}
      </p>
      <Link
        to="/settings"
        className="shrink-0 text-xs underline underline-offset-4 hover:no-underline"
      >
        Review settings
      </Link>
    </div>
  );
}
