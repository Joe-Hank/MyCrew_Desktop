import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Persistent user preferences — survives app restart via localStorage.
 *
 * Add new prefs here rather than scattering useState across components.
 * Each consumer reads its slice (selector) so unrelated re-renders are
 * avoided.
 */

export type LogTab = "应用日志" | "Agent 输出";
export type TeamTab = "agents" | "crews" | "tools";
export type SettingsTab = "llm" | "mcp" | "permission";

interface PrefsState {
  // Inception drawer
  inceptionLlm: string | null;      // provider id, e.g. "prov_xxx"
  inceptionModel: string | null;    // model_name, e.g. "deepseek-v4-pro"
  inceptionThinking: boolean;

  // Log drawer
  logDrawerExpanded: boolean;
  logDrawerActiveTab: LogTab;

  // Team / Settings active tab
  teamActiveTab: TeamTab;
  settingsActiveTab: SettingsTab;

  // Setters
  setInceptionLlm: (v: string | null) => void;
  setInceptionModel: (v: string | null) => void;
  setInceptionThinking: (v: boolean) => void;
  setLogDrawerExpanded: (v: boolean) => void;
  setLogDrawerActiveTab: (v: LogTab) => void;
  setTeamActiveTab: (v: TeamTab) => void;
  setSettingsActiveTab: (v: SettingsTab) => void;
}

export const usePrefsStore = create<PrefsState>()(
  persist(
    (set) => ({
      inceptionLlm: null,
      inceptionModel: null,
      inceptionThinking: false,
      logDrawerExpanded: false,
      logDrawerActiveTab: "应用日志",
      teamActiveTab: "agents",
      settingsActiveTab: "llm",

      setInceptionLlm: (v) => set({ inceptionLlm: v }),
      setInceptionModel: (v) => set({ inceptionModel: v }),
      setInceptionThinking: (v) => set({ inceptionThinking: v }),
      setLogDrawerExpanded: (v) => set({ logDrawerExpanded: v }),
      setLogDrawerActiveTab: (v) => set({ logDrawerActiveTab: v }),
      setTeamActiveTab: (v) => set({ teamActiveTab: v }),
      setSettingsActiveTab: (v) => set({ settingsActiveTab: v }),
    }),
    { name: "mycrew-prefs", version: 1 },
  ),
);
