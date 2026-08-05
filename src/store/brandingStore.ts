import { create } from "zustand";
import api, { type Branding } from "../services/api";

interface BrandingState {
  branding: Branding;
  loaded: boolean;
  load: () => Promise<void>;
}

export const useBrandingStore = create<BrandingState>((set, get) => ({
  branding: {},
  loaded: false,

  load: async () => {
    if (get().loaded) return;
    try {
      const branding = await api.branding.get();
      set({ branding, loaded: true });

      // Applied to the document rather than held in React state: the primary
      // colour is consumed through a CSS variable by every component, so
      // threading it through props would mean touching all of them.
      if (branding.primary_color) {
        document.documentElement.style.setProperty(
          "--brand-primary",
          branding.primary_color,
        );
      }
      if (branding.name) {
        document.title = branding.name;
      }
    } catch {
      // Branding is decoration. Failing to load it must not stop the app.
      set({ loaded: true });
    }
  },
}));
