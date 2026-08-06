import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Editor from "@monaco-editor/react";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Code2,
  ExternalLink,
  FileClock,
  GitPullRequest,
  Play,
} from "lucide-react";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardHeader, CardTitle } from "../components/ui/card";
import { SplitPane } from "../components/ui/split";
import { Alert, ErrorState } from "../components/ui/feedback";
import { Tabs } from "../components/ui/tabs";
import { AgentPanel } from "../components/agent/AgentPanel";
import { PolicyEnglishPanel } from "../components/policy/PolicyEnglishPanel";
import { PolicyHistoryPanel } from "../components/policy/PolicyHistoryPanel";
import { PolicyMetadataPanel } from "../components/policy/PolicyMetadataPanel";
import { PolicySyncBanner } from "../components/policy/PolicySyncBanner";
import { PolicyTestsPanel } from "../components/policy/PolicyTestsPanel";
import { TierBadge } from "../components/safety/TierBadge";
import { useAutoSize } from "../lib/useAutoSize";
import api from "../services/api";
import { useAgentStore } from "../store/agentStore";
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
  | "agent"
  | "tests"
  | "history"
  | "english"
  | "playground";

/**
 * Whether the Rego is on screen.
 *
 * Off by default. Most people arrive here to ask what a policy does or to
 * describe a change, and for them a half-width wall of Rego is the least useful
 * thing on the page. The code is one click away, it reappears on its own when a
 * proposal needs reviewing, and the preference sticks, so anyone who does read
 * Rego turns it on once.
 */
const SHOW_CODE_KEY = "sentinel.policyEditor.showCode";

/** The code pane's share of the width when the code is shown. */
const SPLIT_KEY = "sentinel.policyEditor.split";

function readShowCode(): boolean {
  try {
    return window.localStorage.getItem(SHOW_CODE_KEY) === "true";
  } catch {
    return false;
  }
}

function readSplit(): number {
  try {
    const stored = Number(window.localStorage.getItem(SPLIT_KEY));
    return Number.isFinite(stored) && stored >= 0.2 && stored <= 0.8 ? stored : 0.5;
  } catch {
    return 0.5;
  }
}

function remember(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* A browser refusing storage should not stop the control working. */
  }
}

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
  const setComposerDraft = useAgentStore((s) => s.setComposerDraft);
  const { policyName } = useParams<{ policyName: string }>();
  const [panel, setPanel] = useState<PanelTab>("metadata");
  const [inputJson, setInputJson] = useState(SAMPLE_INPUT);
  const [outputJson, setOutputJson] = useState("{}");
  const [evaluating, setEvaluating] = useState(false);
  const [prUrl, setPrUrl] = useState<string | null>(null);
  const [showCode, setShowCode] = useState(readShowCode);
  const [split, setSplit] = useState(readSplit);

  const toggleCode = (next: boolean) => {
    setShowCode(next);
    remember(SHOW_CODE_KEY, String(next));
  };

  const resize = (next: number) => {
    setSplit(next);
    remember(SPLIT_KEY, String(next));
  };

  useEffect(() => {
    void store.loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The URL is the selection. A scaffolded policy arrives with its draft
  // already seeded by the dashboard and has nothing committed to fetch, so
  // asking for it would 404 — hence the check against what is already open.
  useEffect(() => {
    if (!policyName) return;
    if (store.selectedName === policyName) return;
    void store.select(policyName);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [policyName]);

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

  const codePane = (
    <Card className="flex min-h-0 w-full flex-col overflow-hidden">
      <CardHeader className="flex-row items-center justify-between py-2.5">
        <CardTitle className="truncate font-mono text-xs">
          {store.selectedName ?? "No policy selected"}
        </CardTitle>
        <div className="flex shrink-0 items-center gap-2">
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
  );

  const panelPane = (
    <Card className="flex min-h-0 w-full flex-col overflow-hidden">
      <Tabs
        value={panel}
        onChange={(id) => setPanel(id as PanelTab)}
        items={[
          { id: "metadata", label: "Metadata", count: store.metadata?.rule_count },
          { id: "agent", label: "Assistant" },
          { id: "tests", label: "Tests" },
          { id: "english", label: "Plain English" },
          { id: "history", label: "History", count: store.revisions.length },
          { id: "playground", label: "Playground" },
        ]}
      />

      {/* Not scrollable here: the panels that need to scroll do it inside
          themselves, and the ones showing an editor need a bounded height to
          size against rather than an ancestor that grows to fit them. */}
      <div className="min-h-0 flex-1">
        {panel === "metadata" && (
          <div className="h-full overflow-y-auto">
            <PolicyMetadataPanel
              metadata={store.metadata}
              dirty={dirty}
              onAddRule={(seed) => {
                setComposerDraft(seed);
                setPanel("agent");
              }}
            />
          </div>
        )}

        {panel === "agent" && (
          <div className="h-full p-3">
            <AgentPanel
              policyName={store.selectedName ?? undefined}
              currentContent={store.content}
              onApply={(content, name) => {
                // Into the editor as an unsaved change, so a proposal goes
                // through the same validate-and-PR path a hand-written edit
                // does.
                if (name !== store.selectedName && store.files.includes(name)) {
                  void store.select(name).then(() => store.setContent(content));
                } else {
                  store.setContent(content);
                }
                // The one moment the Rego is worth looking at, so it comes
                // back whether or not the user keeps it on.
                toggleCode(true);
              }}
            />
          </div>
        )}

        {panel === "tests" && (
          <PolicyTestsPanel
            policyName={store.selectedName ?? undefined}
            resourceType={store.metadata?.resource_type}
            ruleIds={store.metadata?.rules.map((r) => r.id) ?? []}
          />
        )}

        {panel === "english" && store.selectedName && (
          <div className="h-full overflow-y-auto">
            <PolicyEnglishPanel
              policyName={store.selectedName}
              content={store.content}
              committedContent={store.committedContent}
            />
          </div>
        )}

        {panel === "history" && (
          <PolicyHistoryPanel
            revisions={store.revisions}
            available={store.historyAvailable}
            uncommitted={store.metadata?.uncommitted_changes}
            policyName={store.selectedName ?? undefined}
            currentContent={store.content}
            onView={store.loadRevision}
            onRestore={store.restoreFromGit}
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
      </div>
    </Card>
  );

  return (
    <div className="mx-auto flex h-full max-w-[1700px] flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Link
            to="/policies"
            className="inline-flex items-center gap-1.5 text-2xs text-content-subtle hover:text-content"
          >
            <ArrowLeft className="size-3.5" />
            All policies
          </Link>
          <h1 className="mt-1 flex items-center gap-2 truncate text-lg font-semibold text-content">
            <span className="truncate font-mono">
              {(policyName ?? "").replace(/\.rego$/, "") || "Policy Editor"}
            </span>
            {maxTier >= 2 && <TierBadge tier={maxTier} />}
          </h1>
          <p className="mt-1 truncate text-xs text-content-muted">
            {store.metadata?.title ??
              "Policies live in git and change by pull request."}
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
            variant={showCode ? "secondary" : "ghost"}
            onClick={() => toggleCode(!showCode)}
            aria-pressed={showCode}
          >
            <Code2 />
            {showCode ? "Hide code" : "Show code"}
          </Button>
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

      {/* Deliberately not folded into the error above. A compile error stops
          you; this does not, and that is what makes it dangerous — the policy
          saves, merges, and reports everything as compliant forever. */}
      {store.validation?.warnings && store.validation.warnings.length > 0 && (
        <Alert
          tone="warning"
          title="This compiles, but some rules can never fire"
        >
          <p className="mb-1.5">
            Rego treats a reference to a field that was never collected as
            simply not matching, so these rules pass every resource and nothing
            reports an error.
          </p>
          <ul className="list-disc space-y-0.5 pl-4">
            {store.validation.warnings.map((warning) => (
              <li key={warning.field}>
                <code className="font-mono">
                  input.resource.{warning.field}
                </code>{" "}
                is not collected for {warning.resource_type}.
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

      {showCode ? (
        <SplitPane
          className="min-h-[520px] flex-1"
          ratio={split}
          onRatioChange={resize}
          left={codePane}
          right={panelPane}
        />
      ) : (
        <div className="flex min-h-[520px] min-w-0 flex-1">{panelPane}</div>
      )}

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
