import { create } from "zustand";

import {
  api,
  type AgentStatus,
  type AgentToolCall,
  type AuthoredPolicy,
  type ChatTurn,
  type FieldWarning,
  type GuardrailViolation,
} from "../services/api";
import { toast } from "./toastStore";

export interface ChatMessage extends ChatTurn {
  id: number;
  /** Which tools the assistant used to answer. Rendered as its working. */
  toolCalls?: AgentToolCall[];
  truncated?: boolean;
  failed?: boolean;
  /**
   * A policy file the assistant proposed in this turn, rendered as a diff.
   * Attached to the message rather than held once for the panel so that
   * scrolling back shows what was proposed at the time, and so a later turn
   * cannot silently replace a diff the user is still reading.
   */
  proposal?: AuthoredPolicy;
  /** Set when the tier ceiling withdrew a proposal from this turn. */
  refusal?: GuardrailViolation;
  /**
   * Fields the proposal reads that discovery never collects.
   *
   * Kept next to the diff rather than shown as a toast, because it is the one
   * thing about a proposal that will not announce itself later: the policy
   * compiles, saves, merges, and then never fires.
   */
  fieldWarnings?: FieldWarning[];
  /** True once the user has taken or dismissed the proposal. */
  resolved?: boolean;
}

interface AgentState {
  status: AgentStatus | null;
  statusLoaded: boolean;

  messages: ChatMessage[];
  asking: boolean;

  /**
   * What is typed but not yet sent.
   *
   * Lives here rather than in the composer so other parts of the editor can put
   * words in it — "Add rule" hands over a half-written request instead of
   * dropping you at an empty box — and so switching tabs mid-sentence does not
   * discard it.
   */
  composerDraft: string;
  setComposerDraft: (value: string) => void;

  loadStatus: () => Promise<void>;
  send: (
    message: string,
    context?: { targetPolicy?: string; openContent?: string },
  ) => Promise<void>;
  resolveProposal: (messageId: number) => void;
  clearChat: () => void;
}

let nextId = 1;

/** How many prior turns to send back. The server caps this too. */
const HISTORY_LIMIT = 8;

export const useAgentStore = create<AgentState>((set, get) => ({
  status: null,
  statusLoaded: false,

  messages: [],
  asking: false,

  composerDraft: "",
  setComposerDraft: (composerDraft) => set({ composerDraft }),

  loadStatus: async () => {
    try {
      const status = await api.agent.status();
      set({ status, statusLoaded: true });
    } catch {
      // A missing or disabled assistant is a normal deployment, not an error
      // worth interrupting the user over. The panel hides itself instead.
      set({ status: null, statusLoaded: true });
    }
  },

  send: async (message, context) => {
    const trimmed = message.trim();
    if (!trimmed || get().asking) return;

    // The history sent is the transcript before this message, so the server
    // does not receive it twice.
    const history: ChatTurn[] = get()
      .messages.slice(-HISTORY_LIMIT)
      .map(({ role, content }) => ({ role, content }));

    set((state) => ({
      messages: [...state.messages, { id: nextId++, role: "user", content: trimmed }],
      asking: true,
    }));

    try {
      const reply = await api.agent.chat({
        message: trimmed,
        history,
        target_policy: context?.targetPolicy,
        open_content: context?.openContent,
      });

      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: nextId++,
            role: "assistant",
            // A reply that is only a policy file would otherwise leave an empty
            // bubble above the diff, which reads as a failure.
            content: reply.answer || "Here is the change.",
            toolCalls: reply.tool_calls,
            truncated: reply.truncated,
            proposal: reply.proposal ?? undefined,
            refusal: reply.refusal ?? undefined,
            fieldWarnings: reply.field_warnings?.length
              ? reply.field_warnings
              : undefined,
          },
        ],
        asking: false,
      }));

      if (reply.refusal) {
        toast.error(
          "The assistant withdrew its change",
          "It asked for an action above the Tier 2 ceiling.",
        );
      } else if (reply.proposal && !reply.proposal.valid) {
        toast.warning(
          "The proposed policy did not compile",
          "Review the validation errors before taking it.",
        );
      } else if (reply.field_warnings?.length) {
        toast.warning(
          "This change would never fire",
          `It reads ${reply.field_warnings[0].field}, which the scanner does not collect.`,
        );
      }
    } catch (error) {
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: nextId++,
            role: "assistant",
            content: error instanceof Error ? error.message : String(error),
            failed: true,
          },
        ],
        asking: false,
      }));
    }
  },

  resolveProposal: (messageId) =>
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === messageId ? { ...message, resolved: true } : message,
      ),
    })),

  clearChat: () => set({ messages: [] }),
}));
