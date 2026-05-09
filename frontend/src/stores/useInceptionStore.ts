import { create } from "zustand";
import type { Blueprint } from "../queries/useInceptionQuery";

interface InceptionState {
  drawerOpen: boolean;
  activeSessionId: string | null;
  draftBlueprint: Blueprint | null;

  openDrawer: () => void;
  closeDrawer: () => void;
  setActiveSession: (id: string | null) => void;
  setDraftBlueprint: (bp: Blueprint | null) => void;
}

export const useInceptionStore = create<InceptionState>((set) => ({
  drawerOpen: false,
  activeSessionId: null,
  draftBlueprint: null,

  openDrawer: () => set({ drawerOpen: true }),
  closeDrawer: () => set({ drawerOpen: false }),
  setActiveSession: (id) => set({ activeSessionId: id, draftBlueprint: null }),
  setDraftBlueprint: (bp) => set({ draftBlueprint: bp }),
}));
