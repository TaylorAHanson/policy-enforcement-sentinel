import { create } from "zustand";
import api, { ApiError, type SettingsSchema } from "../services/api";
import { toast } from "./toastStore";

interface SettingsState {
  schema: SettingsSchema | null;
  loading: boolean;
  saving: string | null;
  error: string | null;

  load: () => Promise<void>;
  update: (key: string, value: unknown) => Promise<boolean>;
  reset: (key: string) => Promise<boolean>;

  /** Whether enforcement is currently switched on, for the global banner. */
  enforcementEnabled: () => boolean;
  destructiveWorkspaces: () => string[];
}

const describe = (e: unknown) =>
  e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);

/**
 * Shared fallback for the workspace list.
 *
 * The getters below are read through `useSettingsStore(s => s.thing())`, and
 * Zustand compares each result to the last one by identity. A fresh `[]` on
 * every call therefore reads as "the store changed", which re-renders, which
 * calls the selector again — an infinite loop that renders as a blank page.
 * Any getter added here must return a stable reference for a given state.
 */
const NO_WORKSPACES: string[] = [];

function findSetting(schema: SettingsSchema | null, key: string) {
  if (!schema) return undefined;
  for (const group of schema.groups) {
    const match = group.fields.find((s) => s.key === key);
    if (match) return match;
  }
  return undefined;
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  schema: null,
  loading: false,
  saving: null,
  error: null,

  load: async () => {
    set({ loading: true, error: null });
    try {
      set({ schema: await api.settings.schema(), loading: false });
    } catch (e) {
      set({ error: describe(e), loading: false });
    }
  },

  update: async (key, value) => {
    set({ saving: key });
    try {
      await api.settings.update(key, value);
      // Refetched rather than patched locally: the backend coerces and
      // validates values, so what it stored may not be what was sent, and the
      // form should show what is actually in effect.
      const schema = await api.settings.schema();
      set({ schema, saving: null });

      const definition = findSetting(schema, key);
      if (definition?.danger) {
        toast.warning(
          `${definition.label} changed`,
          "This setting affects what the Sentinel is allowed to do.",
        );
      } else {
        toast.success("Setting saved", definition?.label ?? key);
      }
      return true;
    } catch (e) {
      set({ saving: null });
      toast.error("Could not save the setting", describe(e));
      return false;
    }
  },

  reset: async (key) => {
    set({ saving: key });
    try {
      await api.settings.reset(key);
      set({ schema: await api.settings.schema(), saving: null });
      toast.success("Reset to default", key);
      return true;
    } catch (e) {
      set({ saving: null });
      toast.error("Could not reset the setting", describe(e));
      return false;
    }
  },

  // Read from the resolved top-level values rather than the form field: the
  // effective setting is whatever the backend computed after environment
  // variables and overrides, which is what the banner must reflect.
  enforcementEnabled: () => Boolean(get().schema?.enforcement_enabled),

  destructiveWorkspaces: () => get().schema?.destructive_workspaces ?? NO_WORKSPACES,
}));
