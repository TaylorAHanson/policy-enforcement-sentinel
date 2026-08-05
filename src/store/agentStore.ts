import { create } from "zustand";

import {
  api,
  ApiError,
  type AgentAnswer,
  type AgentStatus,
  type AgentToolCall,
  type AuthoredPolicy,
  type ChatTurn,
  type GuardrailViolation,
} from "../services/api";
import { toast } from "./toastStore";

export interface ChatMessage extends ChatTurn {
  id: number;
  /** Which tools the assistant used to answer. Rendered as its working. */
  toolCalls?: AgentToolCall[];
  truncated?: boolean;
  failed?: boolean;
}

interface AgentState {
  status: AgentStatus | null;
  statusLoaded: boolean;

  messages: ChatMessage[];
  asking: boolean;

  authoring: boolean;
  proposal: AuthoredPolicy | null;
  /** A 422 from the tier guardrail, kept separate from a transport failure. */
  guardrailViolations: string[];
  guardrailRemedy: string;

  loadStatus: () => Promise<void>;
  ask: (question: string) => Promise<void>;
  clearChat: () => void;
  author: (
    instruction: string,
    context?: { targetPolicy?: string; existingContent?: string },
  ) => Promise<AuthoredPolicy | null>;
  dismissProposal: () => void;
}

let nextId = 1;

/** How many prior turns to send back. The server caps this too. */
const HISTORY_LIMIT = 8;

/** The tier guardrail refusing, as opposed to the request failing. */
function guardrailDetail(error: unknown): GuardrailViolation | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;
  const detail = error.detail as Partial<GuardrailViolation> | undefined;
  if (detail?.error !== "guardrail_violation") return null;
  return {
    error: "guardrail_violation",
    violations: detail.violations ?? [],
    remedy: detail.remedy ?? "",
  };
}

export const useAgentStore = create<AgentState>((set, get) => ({
  status: null,
  statusLoaded: false,

  messages: [],
  asking: false,

  authoring: false,
  proposal: null,
  guardrailViolations: [],
  guardrailRemedy: "",

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

  ask: async (question) => {
    const trimmed = question.trim();
    if (!trimmed || get().asking) return;

    const userMessage: ChatMessage = {
      id: nextId++,
      role: "user",
      content: trimmed,
    };

    // The history sent is the transcript before this question, so the server
    // does not receive the question twice.
    const history: ChatTurn[] = get()
      .messages.slice(-HISTORY_LIMIT)
      .map(({ role, content }) => ({ role, content }));

    set((state) => ({ messages: [...state.messages, userMessage], asking: true }));

    try {
      const answer: AgentAnswer = await api.agent.ask({ question: trimmed, history });
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: nextId++,
            role: "assistant",
            content: answer.answer,
            toolCalls: answer.tool_calls,
            truncated: answer.truncated,
          },
        ],
        asking: false,
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: nextId++,
            role: "assistant",
            content: message,
            failed: true,
          },
        ],
        asking: false,
      }));
    }
  },

  clearChat: () => set({ messages: [] }),

  author: async (instruction, context) => {
    set({ authoring: true, guardrailViolations: [], guardrailRemedy: "" });
    try {
      const proposal = await api.agent.author({
        instruction,
        target_policy: context?.targetPolicy,
        existing_content: context?.existingContent,
      });
      set({ proposal, authoring: false });

      if (!proposal.valid) {
        toast.warning(
          "The draft did not compile",
          "Review the validation errors before saving.",
        );
      }
      return proposal;
    } catch (error) {
      const guardrail = guardrailDetail(error);
      if (guardrail) {
        set({
          authoring: false,
          guardrailViolations: guardrail.violations,
          guardrailRemedy: guardrail.remedy,
        });
        toast.error(
          "The assistant refused this policy",
          "It asked for an action above the Tier 2 ceiling.",
        );
        return null;
      }

      set({ authoring: false });
      toast.error(
        "Could not draft the policy",
        error instanceof Error ? error.message : String(error),
      );
      return null;
    }
  },

  dismissProposal: () =>
    set({ proposal: null, guardrailViolations: [], guardrailRemedy: "" }),
}));
