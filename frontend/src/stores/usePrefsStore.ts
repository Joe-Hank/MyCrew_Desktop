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

  // Most-recently-opened project (used by TaskPage to auto-restore when
  // the user re-enters /tasks without an id — both via the sidebar nav
  // mid-session and across an app restart).
  lastProjectId: string | null;

  // Width (px) of the IO viewer side drawer on the task page. Persisted
  // so the user's preferred reading width survives the session.
  ioViewerWidth: number;

  // Setters
  setInceptionLlm: (v: string | null) => void;
  setInceptionModel: (v: string | null) => void;
  setInceptionThinking: (v: boolean) => void;
  setLogDrawerExpanded: (v: boolean) => void;
  setLogDrawerActiveTab: (v: LogTab) => void;
  setTeamActiveTab: (v: TeamTab) => void;
  setSettingsActiveTab: (v: SettingsTab) => void;
  setLastProjectId: (v: string | null) => void;
  setIoViewerWidth: (v: number) => void;
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
      lastProjectId: null,
      ioViewerWidth: 380,

      setInceptionLlm: (v) => set({ inceptionLlm: v }),
      setInceptionModel: (v) => set({ inceptionModel: v }),
      setInceptionThinking: (v) => set({ inceptionThinking: v }),
      setLogDrawerExpanded: (v) => set({ logDrawerExpanded: v }),
      setLogDrawerActiveTab: (v) => set({ logDrawerActiveTab: v }),
      setTeamActiveTab: (v) => set({ teamActiveTab: v }),
      setSettingsActiveTab: (v) => set({ settingsActiveTab: v }),
      setLastProjectId: (v) => set({ lastProjectId: v }),
      // Clamp 280-1200 — below 280 the JSON tree becomes unreadable;
      // above 1200 the canvas behind gets squeezed off-screen.
      setIoViewerWidth: (v) => set({
        ioViewerWidth: Math.min(1200, Math.max(280, Math.round(v))),
      }),
    }),
    { name: "mycrew-prefs", version: 1 },
  ),
);
