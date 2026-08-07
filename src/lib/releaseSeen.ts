const STORAGE_KEY = "sentinel.releases.seen";

/**
 * The last release version this browser has looked at.
 *
 * Deliberately per-browser rather than per-user on the server: "have you read
 * the release notes" is not worth a table, a migration, and an identity to
 * attach it to. The cost of getting it wrong is one extra dot in a sidebar.
 */
export function lastSeenRelease(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Private browsing and some enterprise policies make localStorage throw.
    return null;
  }
}

export function markReleasesSeen(version: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, version);
  } catch {
    /* Not being able to remember is fine; the dot just stays. */
  }
}

/** True when there is a release this browser has not opened yet. */
export function hasUnreadRelease(latestVersion: string | null): boolean {
  if (!latestVersion) return false;
  const seen = lastSeenRelease();
  // A first visit does not raise the dot. Someone opening the app for the
  // first time has not missed anything.
  if (seen === null) {
    markReleasesSeen(latestVersion);
    return false;
  }
  return seen !== latestVersion;
}
