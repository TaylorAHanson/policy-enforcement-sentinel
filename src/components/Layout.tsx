import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { ErrorBoundary } from "./ErrorBoundary";
import { EnforcementBanner } from "./safety/EnforcementBanner";
import { Sidebar } from "./Sidebar";
import { Toaster } from "./Toaster";
import { hasUnreadRelease } from "../lib/releaseSeen";
import api from "../services/api";
import { useBrandingStore } from "../store/brandingStore";
import { useSettingsStore } from "../store/settingsStore";

export function Layout() {
  const branding = useBrandingStore((s) => s.branding);
  const loadBranding = useBrandingStore((s) => s.load);
  const loadSettings = useSettingsStore((s) => s.load);
  const [unreadReleases, setUnreadReleases] = useState(false);
  const location = useLocation();

  useEffect(() => {
    void loadBranding();
    // Settings are loaded once at the top level because the enforcement banner
    // must be visible on every page, not only on the one that happens to have
    // fetched them.
    void loadSettings();
  }, [loadBranding, loadSettings]);

  useEffect(() => {
    // Re-checked on navigation so the dot clears as soon as the user leaves the
    // releases page, without that page needing to reach back up here.
    void api.releaseNotes
      .latest()
      .then((latest) => setUnreadReleases(hasUnreadRelease(latest.version)))
      .catch(() => setUnreadReleases(false));
  }, [location.pathname]);

  return (
    <div className="flex h-screen bg-canvas font-sans text-content">
      <Sidebar branding={branding} unreadReleases={unreadReleases} />
      <div className="flex min-w-0 flex-1 flex-col">
        <EnforcementBanner />
        <main className="flex-1 overflow-auto p-8">
          {/* Keyed on the path so navigating away from a broken page clears the
              error, instead of the boundary latching until a reload. */}
          <ErrorBoundary key={location.pathname} label="This page failed to render">
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      <Toaster />
    </div>
  );
}
