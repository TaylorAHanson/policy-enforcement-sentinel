/**
 * The local captures, and the one door from them into the committed tests.
 *
 * A capture is a resource document from a real scan, named after a real
 * catalog, schema and volume. That makes it the most useful test here — the
 * exact spellings and nulls the Databricks API produces, which is what every
 * dead rule in this release turned out to hinge on — and the reason it cannot
 * be committed.
 *
 * So this panel exists to make the difference visible. Capturing is safe and
 * unremarkable: the files are gitignored and never leave the machine. Promoting
 * is deliberate, shows exactly which values would be replaced, and refuses when
 * scrubbing would leave something identifying behind or change what the
 * policies do.
 */
import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Upload, ShieldAlert } from "lucide-react";

import { api, type Capture, type PromotionResult } from "../../services/api";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Spinner } from "../ui";

export function CapturesPanel() {
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [directory, setDirectory] = useState("");
  const [loading, setLoading] = useState(true);
  const [promoted, setPromoted] = useState<Record<string, PromotionResult>>({});
  const [failed, setFailed] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.testing.captures();
      setCaptures(data.captures);
      setDirectory(data.directory);
    } catch {
      setCaptures([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-xs text-content-muted">
        <Spinner /> Reading captures…
      </div>
    );
  }

  if (!captures.length) return null;

  const pending = captures.filter((c) => !promoted[c.name]);

  return (
    <div className="rounded-md border border-border bg-surface-raised/40 p-3">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2">
        <h2 className="text-xs font-semibold text-content">
          {captures.length} capture{captures.length === 1 ? "" : "s"} on this
          machine
        </h2>
        <span className="text-2xs text-content-muted">
          Taken from a real scan and named after real resources, so they stay
          here and are never committed. Promoting one replaces the names, keeps
          the shape, and ships it to every deployment.
        </span>
      </div>

      <div className="flex flex-col gap-1">
        {pending.map((capture) => (
          <CaptureRow
            key={capture.name}
            capture={capture}
            error={failed[capture.name]}
            onPromote={async () => {
              try {
                const result = await api.testing.promote(capture.name);
                setPromoted((p) => ({ ...p, [capture.name]: result }));
                setFailed((f) => {
                  const next = { ...f };
                  delete next[capture.name];
                  return next;
                });
              } catch (e) {
                setFailed((f) => ({
                  ...f,
                  [capture.name]: e instanceof Error ? e.message : String(e),
                }));
              }
            }}
          />
        ))}
      </div>

      {Object.keys(promoted).length > 0 && (
        <p className="mt-2 border-t border-border pt-2 text-2xs text-success">
          Promoted{" "}
          {Object.values(promoted)
            .map((p) => p.name)
            .join(", ")}
          . These are new files in the committed tests — review and commit them.
        </p>
      )}

      <p className="mt-2 text-2xs text-content-subtle">{directory}</p>
    </div>
  );
}

function CaptureRow({
  capture,
  error,
  onPromote,
}: {
  capture: Capture;
  error?: string;
  onPromote: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;

  // Blocked before it is attempted. The backend refuses these too — this is so
  // the reason is visible without having to press the button and read an error.
  const blocked = (capture.survivors?.length ?? 0) > 0;

  return (
    <div className="rounded border border-border/60">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-xs text-content hover:text-content"
        >
          <Chevron className="size-3 shrink-0 text-content-muted" />
          <span className="truncate font-mono text-2xs">{capture.name}</span>
          <Badge variant="outline">{capture.resource_type}</Badge>
          {blocked && (
            <Badge variant="danger">
              <ShieldAlert className="size-3" />
              would leak a name
            </Badge>
          )}
        </button>

        <Button
          size="sm"
          variant="outline"
          disabled={busy || blocked}
          onClick={async () => {
            setBusy(true);
            await onPromote();
            setBusy(false);
          }}
        >
          {busy ? <Spinner /> : <Upload />}
          Promote
        </Button>
      </div>

      {open && (
        <div className="border-t border-border/60 px-2 py-2 text-2xs">
          {capture.target_name && (
            <p className="mb-1.5 text-content-muted">
              Would be written as{" "}
              <span className="font-mono text-content">
                {capture.target_name}.json
              </span>
              , named for the rule it demonstrates rather than for a resource.
            </p>
          )}

          {blocked ? (
            <div className="text-danger">
              <p className="mb-1">
                Promotion is refused. These values name something real and the
                scrubber does not recognise the key they arrived under, so they
                would be committed as they are:
              </p>
              <ul className="ml-3 list-disc">
                {capture.survivors?.map((s) => (
                  <li key={s.path}>
                    <span className="font-mono">{s.path}</span> — {s.value}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <>
              <p className="mb-1 text-content-muted">
                Replaced on the way in. Everything else, including the exact
                enum spellings and any nulls, is kept — that is what the capture
                is for.
              </p>
              <ul className="ml-3 list-disc text-content-muted">
                {capture.replacements?.map((r) => (
                  <li key={r.path}>
                    <span className="font-mono text-content">{r.path}</span>:{" "}
                    <span className="line-through">{r.from}</span> → {r.to}
                  </li>
                ))}
              </ul>

              {(capture.withheld?.length ?? 0) > 0 && (
                <p className="mt-1.5 text-warning">
                  This capture records {capture.withheld?.join(", ")} passing,
                  and {capture.withheld?.length === 1 ? "that rule is" : "those rules are"}{" "}
                  already known to be broken. The promoted test will say nothing
                  about {capture.withheld?.length === 1 ? "it" : "them"} rather
                  than vouch for {capture.withheld?.length === 1 ? "it" : "them"},
                  which leaves {capture.withheld?.length === 1 ? "it" : "them"}{" "}
                  visibly untested.
                </p>
              )}
            </>
          )}

          {error && <p className="mt-1.5 text-danger">{error}</p>}
        </div>
      )}
    </div>
  );
}
