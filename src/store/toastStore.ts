import { create } from "zustand";

export type ToastTone = "info" | "success" | "warning" | "danger";

export interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
  /** Milliseconds before auto-dismiss. `null` keeps it until dismissed. */
  duration: number | null;
}

interface ToastState {
  toasts: Toast[];
  push: (toast: Omit<Toast, "id" | "duration"> & { duration?: number | null }) => number;
  dismiss: (id: number) => void;
  clear: () => void;
}

let nextId = 1;

/** How long each tone stays up, in milliseconds. */
const DEFAULT_DURATION: Record<ToastTone, number | null> = {
  info: 4000,
  success: 3000,
  warning: 6000,
  // Errors stay until dismissed. An action that failed against a real
  // workspace is not something to let scroll past while the operator is
  // looking elsewhere.
  danger: null,
};

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],

  push: ({ tone, title, description, duration }) => {
    const id = nextId++;
    const resolved = duration === undefined ? DEFAULT_DURATION[tone] : duration;

    set((state) => ({
      toasts: [...state.toasts, { id, tone, title, description, duration: resolved }],
    }));

    if (resolved != null) {
      setTimeout(() => get().dismiss(id), resolved);
    }
    return id;
  },

  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),

  clear: () => set({ toasts: [] }),
}));

/** Shorthands, so call sites read as a sentence. */
export const toast = {
  info: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: "info", title, description }),
  success: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: "success", title, description }),
  warning: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: "warning", title, description }),
  error: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: "danger", title, description }),
};
