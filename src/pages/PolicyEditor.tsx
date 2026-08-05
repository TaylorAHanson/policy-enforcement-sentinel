import { useEffect, useMemo, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import {
  AlertTriangle,
  Check,
  ExternalLink,
  FileClock,
  GitPullRequest,
  Play,
} from "lucide-react";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Alert, ErrorState, Skeleton } from "../components/ui/feedback";
import { Tabs } from "../components/ui/tabs";
import { AgentChatPanel } from "../components/agent/AgentChatPanel";
import { PolicyAuthorPanel } from "../components/agent/PolicyAuthorPanel";
import { PolicyEnglishPanel } from "../components/policy/PolicyEnglishPanel";
import { PolicyHistoryPanel } from "../components/policy/PolicyHistoryPanel";
import { PolicyMetadataPanel } from "../components/policy/PolicyMetadataPanel";
import { PolicySyncBanner } from "../components/policy/PolicySyncBanner";
import { TierBadge } from "../components/safety/TierBadge";
import { useAutoSize } from "../lib/useAutoSize";
import api from "../services/api";
import { usePolicyStore } from "../store/policyStore";
import { toast } from "../store/toastStore";

const MONACO_OPTIONS = {
  minimap: { enabled: false },
  fontSize: 13,
  lineNumbers: "on" as const,
  scrollBeyondLastLine: false,
  automaticLayout: true,
  tabSize: 2,
  renderWhitespace: "selection" as const,
};

const SAMPLE_INPUT = JSON.stringify(
  {
    workspace: { name: "ws-enterprise-prod", type: "enterprise", environment: "prod" },
    resource: {
      id: "example-cluster",
      type: "cluster",
      cluster_type: "interactive",
      access_mode: "shared",
      tags: {},
    },
    allowlist_records: [],
    request_time: 0,
  },
  null,
  2,
);

type PanelTab =
  | "metadata"
  | "history"
  | "english"
  | "playground"
  | "author"
  | "ask";

/**
 * Its own component so the auto-sizing runs when the tab is actually opened.
 *
 * Measured from the parent, the textarea did not exist yet on the render that
 * set up the layout effect, and nothing it depended on changed when the tab
 * later mounted it — so the height was never applied and the input sat at the
 * browser's two-row default while the result took the rest of the pane.
 */
function PlaygroundPanel({
  input,
  onInputChange,
  output,
  evaluating,
  disabled,
  onEvaluate,
}: {
  input: string;
  onInputChange: (value: string) => void;
  output: string;
  evaluating: boolean;
  disabled: boolean;
  onEvaluate: () => void;
}) {
  // The input grows with its payload and stops at half the pane, so the result
  // always keeps at least half the height.
  const paneRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useAutoSize(inputRef, input, { containerRef: paneRef });

  return (
    <div ref={paneRef} className="flex h-full flex-col gap-2 p-3">
      <div className="flex items-center justify-between">
        <p className="text-2xs text-content-subtle">
          Evaluates the editor's contents, not the committed file.
        </p>
        <Button
          variant="primary"
          size="sm"
          onClick={onEvaluate}
          loading={evaluating}
          disabled={disabled}
        >
          <Play />
          Evaluate
        </Button>
      </div>

      <label className="text-2xs uppercase tracking-wider text-content-subtle">
        Input
      </label>
      <textarea
        ref={inputRef}
        value={input}
        onChange={(e) => onInputChange(e.target.value)}
        spellCheck={false}
        className="w-full shrink-0 resize-none rounded-md border border-border-strong bg-surface-raised px-2.5 py-2 font-mono text-2xs leading-relaxed text-content"
      />

      <label className="text-2xs uppercase tracking-wider text-content-subtle">
        Result
      </label>
      <pre className="min-h-0 flex-1 overflow-auto rounded-md border border-border bg-canvas px-2.5 py-2 font-mono text-2xs leading-relaxed text-content-muted">
        {output}
      </pre>
    </div>
  );
}

export default function PolicyEditor() {
  const store = usePolicyStore();
  const [panel, setPanel] = useState<PanelTab>("metadata");
  const [filter, setFilter] = useState("");
  const [inputJson, setInputJson] = useState(SAMPLE_INPUT);
  const [outputJson, setOutputJson] = useState("{}");
  const [evaluating, setEvaluating] = useState(false);
  const [prUrl, setPrUrl] = useState<string | null>(null);

  useEffect(() => {
    void store.loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!store.selectedName && store.files.length) {
      void store.select(store.files[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.files, store.selectedName]);

  const visibleFiles = useMemo(
    () => store.files.filter((f) => f.toLowerCase().includes(filter.toLowerCase())),
    [store.files, filter],
  );

  const dirty = store.isDirty();
  const maxTier = store.metadata?.max_tier ?? 0;

  const evaluate = async () => {
    if (!store.selectedName) return;
    setEvaluating(true);
    try {
      const parsed = JSON.parse(inputJson);
      const pkg = store.metadata?.package ?? store.selectedName.replace(/\.rego$/, "");
      const result = await api.policies.evaluate({
        policy_name: store.selectedName,
        content: store.content,
        query: `data.databricks.governance.${pkg}`,
        input_data: parsed,
      });
      setOutputJson(
        JSON.stringify(result.success ? result.result : { error: result.error }, null, 2),
      );
    } catch (e) {
      const message = e instanceof SyntaxError ? "Input is not valid JSON." : String(e);
      setOutputJson(JSON.stringify({ error: message }, null, 2));
      toast.error("Could not evaluate", message);
    } finally {
      setEvaluating(false);
    }
  };

  const openPr = async () => {
    const url = await store.createPr();
    if (url) setPrUrl(url);
  };

  if (store.error && !store.files.length) {
    return <ErrorState message={store.error} onRetry={() => void store.loadAll()} />;
  }

  return (
    <div className="mx-auto flex h-full max-w-[1700px] flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-content">Policy Editor</h1>
          <p className="mt-1 text-xs text-content-muted">
            Policies live in git and change by pull request. Everything ships at
            Tier 1 — escalating a rule is a deliberate edit.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {dirty && (
            <span className="inline-flex items-center gap-1.5 text-2xs text-content-subtle">
              <FileClock className="size-3.5" />
              Unsubmitted draft, saved in this browser
              <button
                type="button"
                onClick={() => store.discardDraft()}
                className="underline underline-offset-2 hover:text-content"
              >
                Discard
              </button>
            </span>
          )}
          <Button
            variant="secondary"
            onClick={() => void store.validate()}
            disabled={!store.selectedName}
          >
            <Check />
            Validate
          </Button>
          <Button
            variant="primary"
            onClick={() => void openPr()}
            loading={store.submitting}
            disabled={!dirty || !store.githubEnabled}
          >
            <GitPullRequest />
            Open PR to {store.targetBranch}
          </Button>
        </div>
      </header>

      {!store.githubEnabled && (
        <Alert tone="warning" title="Policies are read-only here">
          Policies are stored in git and changed by pull request, and GitHub is
          not configured for this deployment. Set <code>GITHUB_TOKEN</code> and{" "}
          <code>GITHUB_REPO</code> to propose changes from the editor.
        </Alert>
      )}

      <PolicySyncBanner
        sync={store.sync}
        onRefresh={() => void store.refreshFromGit()}
      />

      {prUrl && (
        <Alert
          tone="success"
          title="Pull request opened"
          action={
            <a
              href={prUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs underline underline-offset-4"
            >
              Open <ExternalLink className="size-3" />
            </a>
          }
        >
          Your draft is now a reviewable change. It takes effect once the pull
          request merges and the working copy syncs.
        </Alert>
      )}

      {store.validation && !store.validation.valid && (
        <Alert tone="danger" title="This policy does not compile">
          <ul className="list-disc space-y-0.5 pl-4">
            {store.validation.errors.map((err, i) => (
              <li key={i} className="font-mono">
                {err}
              </li>
            ))}
          </ul>
        </Alert>
      )}

      {maxTier >= 2 && (
        <Alert
          tone={maxTier >= 3 ? "enforcement" : "warning"}
          title={`This policy requests Tier ${maxTier} actions`}
        >
          {maxTier >= 3
            ? "It can permanently remove resources when all five gates agree. Review the rules below carefully."
            : "It can change resources. Those changes are reversible and their undo payloads are stored before anything is applied."}
        </Alert>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-12 gap-4">
        {/* Policy list */}
        <Card className="col-span-12 flex flex-col overflow-hidden lg:col-span-2">
          <div className="border-b border-border p-2">
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter policies"
              className="h-7 text-2xs"
            />
          </div>
          <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
            {store.loading && !store.files.length
              ? Array.from({ length: 8 }).map((_, i) => (
                  <Skeleton key={i} className="h-7 w-full" />
                ))
              : visibleFiles.map((file) => {
                  const meta = store.registry?.policies.find((p) => p.name === file);
                  const active = file === store.selectedName;
                  return (
                    <button
                      key={file}
                      type="button"
                      onClick={() => void store.select(file)}
                      className={`flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-left text-2xs transition-colors ${
                        active
                          ? "bg-accent-subtle text-accent"
                          : "text-content-muted hover:bg-surface-raised hover:text-content"
                      }`}
                    >
                      <span className="min-w-0 flex-1 truncate">
                        {file.replace(/\.rego$/, "")}
                      </span>
                      {meta && meta.max_tier >= 2 && (
                        <TierBadge tier={meta.max_tier} showLabel={false} />
                      )}
                    </button>
                  );
                })}
          </nav>
        </Card>

        {/* Editor */}
        <Card className="col-span-12 flex min-h-[520px] flex-col overflow-hidden lg:col-span-6">
          <CardHeader className="flex-row items-center justify-between py-2.5">
            <CardTitle className="font-mono text-xs">
              {store.selectedName ?? "No policy selected"}
            </CardTitle>
            <div className="flex items-center gap-2">
              {dirty && <Badge variant="warning">unsaved</Badge>}
              {store.metadata && (
                <Badge variant="outline">{store.metadata.rule_count} rules</Badge>
              )}
            </div>
          </CardHeader>
          <div className="min-h-0 flex-1">
            <Editor
              height="100%"
              language="rego"
              theme="vs-dark"
              value={store.content}
              onChange={(value) => store.setContent(value ?? "")}
              options={MONACO_OPTIONS}
            />
          </div>
        </Card>

        {/* Side panel */}
        <Card className="col-span-12 flex min-h-[520px] flex-col overflow-hidden lg:col-span-4">
          <Tabs
            value={panel}
            onChange={(id) => setPanel(id as PanelTab)}
            items={[
              { id: "metadata", label: "Metadata", count: store.metadata?.rule_count },
              { id: "history", label: "History", count: store.revisions.length },
              { id: "english", label: "Plain English" },
              { id: "playground", label: "Playground" },
              { id: "author", label: "Draft" },
              { id: "ask", label: "Ask" },
            ]}
          />

          <div className="min-h-0 flex-1 overflow-y-auto">
            {panel === "metadata" && (
              <PolicyMetadataPanel metadata={store.metadata} dirty={dirty} />
            )}

            {panel === "history" && (
              <PolicyHistoryPanel
                revisions={store.revisions}
                available={store.historyAvailable}
                uncommitted={store.metadata?.uncommitted_changes}
                policyName={store.selectedName ?? undefined}
                onView={store.loadRevision}
                onRestore={store.restoreFromGit}
              />
            )}

            {panel === "english" && store.selectedName && (
              <PolicyEnglishPanel
                policyName={store.selectedName}
                content={store.content}
              />
            )}

            {panel === "playground" && (
              <PlaygroundPanel
                input={inputJson}
                onInputChange={setInputJson}
                output={outputJson}
                evaluating={evaluating}
                disabled={!store.selectedName}
                onEvaluate={() => void evaluate()}
              />
            )}

            {panel === "author" && (
              <PolicyAuthorPanel
                policyName={store.selectedName ?? undefined}
                currentContent={store.content}
                onApply={(content, name) => {
                  // Into the editor as an unsaved change, so the draft goes
                  // through the same validate-and-save path a hand-written
                  // edit does.
                  if (name !== store.selectedName && store.files.includes(name)) {
                    void store.select(name).then(() => store.setContent(content));
                  } else {
                    store.setContent(content);
                  }
                  setPanel("metadata");
                }}
              />
            )}

            {panel === "ask" && (
              <div className="h-full p-3">
                <AgentChatPanel
                  contextNote={store.selectedName ?? undefined}
                />
              </div>
            )}
          </div>
        </Card>
      </div>

      {store.registry && store.registry.summary.max_tier <= 1 && (
        <p className="flex items-center gap-1.5 text-2xs text-content-subtle">
          <AlertTriangle className="size-3" aria-hidden />
          All {store.registry.summary.rule_count} rules across{" "}
          {store.registry.summary.policy_count} policies currently request notify-level
          actions only. Nothing in this repository can destroy a resource as shipped.
        </p>
      )}
    </div>
  );
}
