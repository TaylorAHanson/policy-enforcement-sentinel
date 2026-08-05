import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import GithubSlugger from "github-slugger";
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

interface Section {
  id: string;
  text: string;
}

interface Outline {
  version: string;
  title: string;
  /** The card's DOM id, and the anchor key the nav highlights. */
  anchor: string;
  sections: Section[];
}

/**
 * The `##` headings of one release body, slugged the way rehype-slug will slug
 * them when the same markdown is rendered.
 *
 * Both sides run github-slugger over the headings in document order, so the
 * duplicate counters agree and the nav's ids match the rendered ones.
 */
function sectionsOf(body: string): Section[] {
  const slugger = new GithubSlugger();
  const sections: Section[] = [];
  let inCodeBlock = false;

  for (const line of body.split("\n")) {
    if (line.trim().startsWith("```")) {
      inCodeBlock = !inCodeBlock;
      continue;
    }
    if (inCodeBlock) continue;

    const match = line.match(/^##\s+(.+)$/);
    if (!match) continue;

    // Match the rendered text, since that is what rehype-slug sees.
    const text = match[1]
      .trim()
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/[`*_~]/g, "");

    sections.push({ id: slugger.slug(text), text });
  }

  return sections;
}

/**
 * What changed, newest first.
 *
 * Visiting this page is what clears the unread dot in the sidebar. Tying it
 * to the visit rather than to a dismiss button means the dot means "you have
 * not looked at this yet", which is the only thing it could usefully mean.
 *
 * The releases stay in one continuous column rather than being shown one at a
 * time, because release notes are read through. The nav exists so that reading
 * deep into one release does not strand you: it is a map of where you are, not
 * a filter.
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

  const outlines = useMemo<Outline[]>(
    () =>
      releases.map((release) => ({
        version: release.version,
        title: release.title,
        anchor: `release-${release.version}`,
        sections: sectionsOf(release.body),
      })),
    [releases],
  );

  // Which anchor the reader is currently under. Derived from position on every
  // scroll rather than from clicks, so it stays right when they scroll by hand.
  useEffect(() => {
    if (!outlines.length) return;

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
  }, [outlines]);

  const scrollTo = useCallback((anchor: string, sectionId?: string) => {
    const card = document.getElementById(anchor);
    if (!card) return;

    let target: HTMLElement = card;
    if (sectionId) {
      const heading = Array.from(card.querySelectorAll<HTMLElement>("h2[id]")).find(
        (node) => node.id === sectionId,
      );
      if (heading) target = heading;
    }

    // Held until the reader scrolls for themselves. The last sections sit too
    // close to the end of the document to ever reach the top of the viewport,
    // so position alone would highlight the wrong entry for them however much
    // trailing space the page has.
    const key = sectionId ? `${anchor}::${sectionId}` : anchor;
    pinned.current = key;
    setActive(key);

    target.scrollIntoView({ behavior: "smooth", block: "start" });
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
        <div className="flex items-start gap-8">
          <ReleaseNav
            outlines={outlines}
            active={active}
            onNavigate={scrollTo}
          />

          {/* Enough trailing space that the late sections land somewhere
              readable when jumped to, but not so much that the end of the page
              looks like a rendering failure. The last one still cannot reach
              the top, which is why the scroll-spy has a bottom case. */}
          <div className="min-w-0 flex-1 space-y-6 pb-[40vh]">
            {releases.map((release, index) => (
              <Card
                key={release.version}
                id={`release-${release.version}`}
                data-anchor={`release-${release.version}`}
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
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      rehypePlugins={[rehypeSlug]}
                      components={{
                        // `node` is pulled out so react-markdown's AST node is
                        // not spread onto the DOM element. The id comes from
                        // rehype-slug; data-anchor is what the nav tracks.
                        h2: ({ node: _node, ...props }) => (
                          <h2
                            {...props}
                            data-anchor={`release-${release.version}::${props.id ?? ""}`}
                            className="scroll-mt-6"
                          />
                        ),
                      }}
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

function ReleaseNav({
  outlines,
  active,
  onNavigate,
}: {
  outlines: Outline[];
  active: string | null;
  onNavigate: (anchor: string, sectionId?: string) => void;
}) {
  return (
    <nav
      aria-label="Releases"
      className="sticky top-0 hidden max-h-[calc(100vh-8rem)] w-52 shrink-0 overflow-y-auto lg:block"
    >
      <p className="mb-2 text-2xs font-medium tracking-wide text-content-subtle uppercase">
        Releases
      </p>

      <ul className="space-y-3 border-l border-border">
        {outlines.map((outline) => {
          const onRelease =
            active === outline.anchor || active?.startsWith(`${outline.anchor}::`);

          return (
            <li key={outline.version}>
              <button
                type="button"
                onClick={() => onNavigate(outline.anchor)}
                className={cn(
                  "-ml-px block w-full border-l-2 py-0.5 pl-3 text-left text-xs transition-colors",
                  onRelease
                    ? "border-l-accent font-medium text-content"
                    : "border-l-transparent text-content-muted hover:text-content",
                )}
              >
                <span className="font-mono">v{outline.version}</span>
                <span className="mt-0.5 block truncate text-2xs text-content-subtle">
                  {outline.title}
                </span>
              </button>

              {outline.sections.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {outline.sections.map((section) => {
                    const anchor = `${outline.anchor}::${section.id}`;
                    return (
                      <li key={section.id}>
                        <button
                          type="button"
                          onClick={() => onNavigate(outline.anchor, section.id)}
                          title={section.text}
                          className={cn(
                            "-ml-px block w-full truncate border-l-2 py-0.5 pl-5 text-left text-2xs transition-colors",
                            active === anchor
                              ? "border-l-accent text-content"
                              : "border-l-transparent text-content-subtle hover:text-content-muted",
                          )}
                        >
                          {section.text}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
