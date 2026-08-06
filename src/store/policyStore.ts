import { create } from "zustand";
import api, {
  ApiError,
  type FieldWarning,
  type PolicyMetadata,
  type PolicyRegistry,
  type PolicyRevision,
  type PolicySyncStatus,
} from "../services/api";
import { toast } from "./toastStore";

interface PolicyState {
  files: string[];
  registry: PolicyRegistry | null;
  githubEnabled: boolean;
  targetBranch: string;
  sync: PolicySyncStatus | null;

  selectedName: string | null;
  content: string;
  /** The policy as it is on the target branch, for the dirty comparison. */
  committedContent: string;
  metadata: PolicyMetadata | null;
  revisions: PolicyRevision[];
  historyAvailable: boolean;

  loading: boolean;
  submitting: boolean;
  error: string | null;
  validation: {
    valid: boolean;
    errors: string[];
    /** Compiles, but reads data nothing collects — so it can never fire. */
    warnings?: FieldWarning[];
  } | null;

  loadAll: () => Promise<void>;
  select: (name: string) => Promise<void>;
  /** Open a scaffolded policy that has no committed version yet. */
  startDraft: (name: string, content: string) => void;
  setContent: (content: string) => void;
  discardDraft: () => void;
  validate: () => Promise<boolean>;
  createPr: () => Promise<string | null>;
  retire: () => Promise<string | null>;
  refreshFromGit: () => Promise<void>;
  restoreFromGit: () => Promise<void>;
  loadRevision: (sha: string) => Promise<string | null>;

  isDirty: () => boolean;
}

const describe = (e: unknown) =>
  e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);

// --- Drafts -----------------------------------------------------------------
//
// Policies live in git and change by pull request, so there is nowhere to
// "save" an edit that is not finished. A draft is personal, unreviewed
// work-in-progress: it belongs to this browser and never leaves it. Keeping it
// here means a refresh, a stray navigation, or a closed tab does not cost the
// user their work, without pretending the change has been recorded anywhere
// others can see.

const DRAFT_PREFIX = "sentinel:policy-draft:";

const draftKey = (name: string) => `${DRAFT_PREFIX}${name}`;

const readDraft = (name: string): string | null => {
  try {
    return window.localStorage.getItem(draftKey(name));
  } catch {
    // Private browsing and storage-disabled setups throw on access. Losing
    // drafts is a worse experience, not a broken editor.
    return null;
  }
};

const writeDraft = (name: string, content: string, committed: string) => {
  try {
    if (content === committed) window.localStorage.removeItem(draftKey(name));
    else window.localStorage.setItem(draftKey(name), content);
  } catch {
    /* see readDraft */
  }
};

const clearDraft = (name: string) => {
  try {
    window.localStorage.removeItem(draftKey(name));
  } catch {
    /* see readDraft */
  }
};

export const usePolicyStore = create<PolicyState>((set, get) => ({
  files: [],
  registry: null,
  githubEnabled: false,
  targetBranch: "main",
  sync: null,

  selectedName: null,
  content: "",
  committedContent: "",
  metadata: null,
  revisions: [],
  historyAvailable: false,

  loading: false,
  submitting: false,
  error: null,
  validation: null,

  loadAll: async () => {
    set({ loading: true, error: null });
    try {
      // The registry shells out to OPA and can fail independently of the file
      // listing. A broken policy must not make the editor unreachable — the
      // editor is where it gets fixed.
      const [files, config, registry, sync] = await Promise.all([
        api.policies.list(),
        api.policies.config().catch(() => ({
          github_enabled: false,
          target_branch: "main",
        })),
        api.policies.registry().catch(() => null),
        api.policies.syncStatus().catch(() => null),
      ]);

      set({
        files,
        registry,
        sync,
        githubEnabled: config.github_enabled,
        targetBranch: config.target_branch,
        historyAvailable: registry?.history_available ?? false,
        loading: false,
      });
    } catch (e) {
      set({ error: describe(e), loading: false });
    }
  },

  select: async (name) => {
    set({
      selectedName: name,
      loading: true,
      error: null,
      validation: null,
      metadata: null,
      revisions: [],
    });

    try {
      const [policy, metadata, history] = await Promise.all([
        api.policies.get(name),
        api.policies.metadata(name).catch(() => null),
        api.policies.history(name).catch(() => null),
      ]);

      if (get().selectedName !== name) return;

      // An unsubmitted draft wins over the committed file, so switching away
      // from a policy and back does not silently throw the edit away.
      const draft = readDraft(name);

      set({
        content: draft ?? policy.content,
        committedContent: policy.content,
        metadata,
        revisions: history?.revisions ?? [],
        historyAvailable: history?.available ?? false,
        loading: false,
      });
    } catch (e) {
      if (get().selectedName !== name) return;
      set({ error: describe(e), loading: false });
    }
  },

  /**
   * Open a policy that does not exist on the branch yet.
   *
   * A scaffolded policy has no committed version to fetch, so `select` would
   * 404 on it. Seeding the draft directly means a new policy reaches the editor
   * by the same path as any other unsaved edit, and the empty
   * `committedContent` is what makes it read as dirty — which it is, entirely.
   */
  startDraft: (name, content) => {
    writeDraft(name, content, "");
    set({
      selectedName: name,
      content,
      committedContent: "",
      metadata: null,
      revisions: [],
      validation: null,
      error: null,
      loading: false,
    });
  },

  setContent: (content) => {
    const { selectedName, committedContent } = get();
    if (selectedName) writeDraft(selectedName, content, committedContent);
    set({ content, validation: null });
  },

  discardDraft: () => {
    const { selectedName, committedContent } = get();
    if (selectedName) clearDraft(selectedName);
    set({ content: committedContent, validation: null });
  },

  isDirty: () => get().content !== get().committedContent,

  validate: async () => {
    const { selectedName, content } = get();
    if (!selectedName) return false;

    try {
      const result = await api.policies.validate(selectedName, content);
      set({ validation: result });
      if (!result.valid) {
        toast.error("Policy has errors", result.errors.join("; "));
      } else if (result.warnings?.length) {
        // Valid is not the same as working, and this is the gap between them:
        // the compiler is happy and the rule can never match.
        toast.warning(
          "Compiles, but would never fire",
          `${result.warnings[0].field} is not collected for this resource type.`,
        );
      }
      return result.valid;
    } catch (e) {
      const message = describe(e);
      set({ validation: { valid: false, errors: [message] } });
      toast.error("Validation failed", message);
      return false;
    }
  },

  createPr: async () => {
    const { selectedName, content } = get();
    if (!selectedName) return null;

    // A policy that does not compile takes the whole namespace down at the next
    // evaluation, not just this file. Catching it here costs a round trip;
    // catching it after the merge costs a scan.
    if (!(await get().validate())) return null;

    set({ submitting: true });
    try {
      const result = await api.policies.createPr(selectedName, content);
      // The draft has become a reviewable change, so it is no longer local
      // work-in-progress. The editor keeps showing it until the PR merges and
      // the next sync brings it down as the committed version.
      clearDraft(selectedName);
      set({ submitting: false });
      toast.success(
        "Pull request opened",
        result.explanation_committed
          ? "The policy and its plain-English version are both in the diff."
          : result.pr_url,
      );
      return result.pr_url;
    } catch (e) {
      set({ submitting: false });
      toast.error("Could not open a pull request", describe(e));
      return null;
    }
  },

  retire: async () => {
    const { selectedName } = get();
    if (!selectedName) return null;

    set({ submitting: true });
    try {
      const result = await api.policies.remove(selectedName);
      set({ submitting: false });
      toast.success("Pull request opened", `Retires ${selectedName}.`);
      return result.pr_url;
    } catch (e) {
      set({ submitting: false });
      toast.error("Could not propose retiring the policy", describe(e));
      return null;
    }
  },

  refreshFromGit: async () => {
    try {
      const sync = await api.policies.sync();
      set({ sync });

      // A sync can add, remove, or rewrite policies, so the listing and the
      // parsed registry are both stale afterwards.
      const [files, registry] = await Promise.all([
        api.policies.list(),
        api.policies.registry().catch(() => null),
      ]);
      set({ files, registry });

      const changed = sync.written.length + sync.removed.length;
      toast.success(
        "Working copy refreshed",
        changed ? `${changed} file(s) changed.` : "Already up to date.",
      );
    } catch (e) {
      toast.error("Could not refresh from git", describe(e));
    }
  },

  restoreFromGit: async () => {
    const { selectedName } = get();
    if (!selectedName) return;

    set({ submitting: true });
    try {
      await api.policies.restore(selectedName);

      // Metadata carries the uncommitted flag the warning is based on, so it
      // has to be re-read rather than assumed cleared.
      const metadata = await api.policies
        .metadata(selectedName)
        .catch(() => get().metadata);

      set({ metadata, submitting: false });
      toast.success(
        "Working copy restored",
        `${selectedName} now matches the last commit.`,
      );
    } catch (e) {
      set({ submitting: false });
      toast.error("Could not restore the working copy", describe(e));
    }
  },

  loadRevision: async (sha) => {
    const { selectedName } = get();
    if (!selectedName) return null;
    try {
      const result = await api.policies.revision(selectedName, sha);
      return result.content;
    } catch (e) {
      toast.error("Could not load that revision", describe(e));
      return null;
    }
  },
}));
