import { useCallback, useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { Badge } from "../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "../components/ui/feedback";
import { cn } from "../lib/utils";
import api, { type Release } from "../services/api";
import { markReleasesSeen } from "../lib/releaseSeen";

/** Where the sticky nav sits, and how far above a target we stop scrolling. */
const SCROLL_OFFSET = 96;

/** The card's DOM id, and the key the nav highlights. */
const anchorFor = (version: string) => `release-${version}`;

/**
 * What changed, newest first.
 *
 * Visiting this page is what clears the unread dot in the sidebar. Tying it
 * to the visit rather than to a dismiss button means the dot means "you have
 * not looked at this yet", which is the only thing it could usefully mean.
 *
 * The releases stay in one continuous column rather than being shown one at a
 * time, because release notes are read through. The nav lists versions and
 * nothing else: it also listed every `##` heading, which for a release with
 * twenty sections filled the column with a wall of small grey text and made the
 * versions — the only thing anyone navigates by — impossible to pick out.
 */
export default function ReleaseNotes() {
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  /** A nav entry chosen by clicking, which position must not overrule. */
  const pinned = useRef<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.releaseNotes.list();
      setReleases(result.releases);
      if (result.latest_version) markReleasesSeen(result.latest_version);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  // Which release the reader is currently under. Derived from position on every
  // scroll rather than from clicks, so it stays right when they scroll by hand.
  useEffect(() => {
    if (!releases.length) return;

    const scroller = document.querySelector("main");
    if (!scroller) return;

    let frame = 0;
    const update = () => {
      frame = 0;
      // A clicked target that cannot reach the activation line would otherwise
      // be overruled by position the moment the smooth scroll lands.
      if (pinned.current) return;
      const nodes = Array.from(
        document.querySelectorAll<HTMLElement>("[data-anchor]"),
      );

      // At the bottom the last sections can never reach the activation line,
      // however much trailing space there is — the container simply runs out
      // of scroll. Without this they are permanently unhighlightable, which
      // reads as the nav being broken rather than the page having ended.
      const atBottom =
        scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2;
      if (atBottom) {
        setActive(nodes[nodes.length - 1]?.dataset.anchor ?? null);
        return;
      }

      let current = nodes[0]?.dataset.anchor ?? null;
      for (const node of nodes) {
        if (node.getBoundingClientRect().top > SCROLL_OFFSET + 24) break;
        current = node.dataset.anchor ?? current;
      }
      setActive(current);
    };

    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(update);
    };

    // Scrolling by hand is what hands control back to position. Waiting for the
    // smooth scroll to settle instead cannot work, because its own scroll
    // events are indistinguishable from the reader's.
    const release = () => {
      if (!pinned.current) return;
      pinned.current = null;
      onScroll();
    };

    update();
    scroller.addEventListener("scroll", onScroll, { passive: true });
    scroller.addEventListener("wheel", release, { passive: true });
    scroller.addEventListener("touchmove", release, { passive: true });
    window.addEventListener("keydown", release);

    return () => {
      scroller.removeEventListener("scroll", onScroll);
      scroller.removeEventListener("wheel", release);
      scroller.removeEventListener("touchmove", release);
      window.removeEventListener("keydown", release);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [releases]);

  const scrollTo = useCallback((anchor: string) => {
    const card = document.getElementById(anchor);
    if (!card) return;

    // Held until the reader scrolls for themselves. The last release sits too
    // close to the end of the document to ever reach the top of the viewport,
    // so position alone would highlight the wrong entry for it however much
    // trailing space the page has.
    pinned.current = anchor;
    setActive(anchor);

    card.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  if (loading && !releases.length) {
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-3xl">
        <ErrorState message={error} onRetry={() => void load()} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl">
      <header className="mb-6">
        <h1 className="text-lg font-semibold text-content">Release Notes</h1>
        <p className="mt-1 text-xs text-content-muted">
          Behaviour changes, newest first. Anything that changes what the system
          will do to a resource is written up here.
        </p>
      </header>

      {!releases.length ? (
        <EmptyState
          icon={<Sparkles className="size-8" />}
          title="No release notes yet"
          description="Add a Markdown file to docs/release-notes/ and it will appear here."
        />
      ) : (
        <div className="flex items-start gap-6">
          <ReleaseNav
            releases={releases}
            active={active}
            onNavigate={scrollTo}
          />

          {/* Enough trailing space that the oldest release lands somewhere
              readable when jumped to, but not so much that the end of the page
              looks like a rendering failure. It still cannot reach the top,
              which is why the scroll-spy has a bottom case. */}
          <div className="min-w-0 flex-1 space-y-6 pb-[40vh]">
            {releases.map((release, index) => (
              <Card
                key={release.version}
                id={anchorFor(release.version)}
                data-anchor={anchorFor(release.version)}
                className="scroll-mt-6"
              >
                <CardHeader className="gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle>{release.title}</CardTitle>
                    <Badge variant={index === 0 ? "info" : "outline"}>
                      v{release.version}
                    </Badge>
                    {index === 0 && <Badge variant="success">latest</Badge>}
                    {release.date && (
                      <span className="text-2xs text-content-subtle">
                        {release.date}
                      </span>
                    )}
                  </div>
                  {release.highlight && (
                    <p className="text-xs leading-relaxed text-content-muted">
                      {release.highlight}
                    </p>
                  )}
                </CardHeader>
                <CardContent>
                  <div className="prose-sentinel text-xs">
                    {/* rehype-slug still gives every heading an id, so a link
                        to one from elsewhere keeps working even though the nav
                        no longer lists them. */}
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      rehypePlugins={[rehypeSlug]}
                    >
                      {release.body}
                    </ReactMarkdown>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Version numbers, and nothing else. The list is short enough to read at a glance. */
function ReleaseNav({
  releases,
  active,
  onNavigate,
}: {
  releases: Release[];
  active: string | null;
  onNavigate: (anchor: string) => void;
}) {
  return (
    <nav
      aria-label="Releases"
      className="sticky top-0 hidden max-h-[calc(100vh-8rem)] w-20 shrink-0 overflow-y-auto lg:block"
    >
      <ul className="border-l border-border">
        {releases.map((release) => {
          const anchor = anchorFor(release.version);
          return (
            <li key={release.version}>
              <button
                type="button"
                onClick={() => onNavigate(anchor)}
                className={cn(
                  "-ml-px block w-full border-l-2 py-1 pl-3 text-left font-mono text-xs transition-colors",
                  active === anchor
                    ? "border-l-accent font-medium text-content"
                    : "border-l-transparent text-content-muted hover:text-content",
                )}
              >
                v{release.version}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
