import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Persistent user preferences — survives app restart via localStorage.
 *
 * Add new prefs here rather than scattering useState across components.
 * Each consumer reads its slice (selector) so unrelated re-renders are
 * avoided.
 */

// 2026-05-17: "应用日志" promoted to a 「后端」 sink that now streams
// the full structlog tap (via WS `log.line` + GET /logs replay). The
// new 「LLM 调用」 tab pairs llm.call.detail events by call_id.
export type LogTab = "后端日志" | "Agent 输出" | "LLM 调用";
export type TeamTab = "agents" | "crews" | "tools";
export type SettingsTab = "llm" | "mcp" | "permission";
// 2026-05-21: home page top-left toggle. Categories are scoped to the
// kind of project the user is browsing — drives which template_id
// patterns the project grid shows. Default 'unity' matches the
// historical product focus; AI 视频 / PPT 视频 are the lightweight
// scenarios the project is pivoting toward (see docs/personal_journey_short).
export type HomeCategory = "unity" | "ai_video" | "ppt";

export interface LogDrawerFilters {
  level: "" | "debug" | "info" | "warning" | "error";
  source: string;  // "" = all
  query: string;
}

interface PrefsState {
  // Inception drawer
  inceptionLlm: string | null;      // provider id, e.g. "prov_xxx"
  inceptionModel: string | null;    // model_name, e.g. "deepseek-v4-pro"

  // Log drawer
  logDrawerExpanded: boolean;
  logDrawerActiveTab: LogTab;
  logDrawerHeight: number;
  logDrawerFilters: LogDrawerFilters;

  // Team / Settings active tab
  teamActiveTab: TeamTab;
  settingsActiveTab: SettingsTab;

  // Home page category toggle (Unity / AI 视频 / PPT 视频).
  homeCategory: HomeCategory;

  // Most-recently-opened project (used by TaskPage to auto-restore when
  // the user re-enters /tasks without an id — both via the sidebar nav
  // mid-session and across an app restart).
  lastProjectId: string | null;

  // Width (px) of the IO viewer side drawer on the task page. Persisted
  // so the user's preferred reading width survives the session.
  ioViewerWidth: number;

  // Last parent directory the user picked in ScaffoldConfigModal.
  // Used to pre-fill the modal next time so they don't re-pick the
  // same F:\UnityProjects (or wherever). Null = never set; the modal
  // falls back to the OS desktop folder.
  scaffoldParent: string | null;

  // Setters
  setInceptionLlm: (v: string | null) => void;
  setInceptionModel: (v: string | null) => void;
  setLogDrawerExpanded: (v: boolean) => void;
  setLogDrawerActiveTab: (v: LogTab) => void;
  setLogDrawerHeight: (v: number) => void;
  setLogDrawerFilters: (patch: Partial<LogDrawerFilters>) => void;
  setTeamActiveTab: (v: TeamTab) => void;
  setSettingsActiveTab: (v: SettingsTab) => void;
  setHomeCategory: (v: HomeCategory) => void;
  setLastProjectId: (v: string | null) => void;
  setIoViewerWidth: (v: number) => void;
  setScaffoldParent: (v: string | null) => void;
}

export const usePrefsStore = create<PrefsState>()(
  persist(
    (set) => ({
      inceptionLlm: null,
      inceptionModel: null,
      logDrawerExpanded: false,
      logDrawerActiveTab: "后端日志",
      logDrawerHeight: 224,
      logDrawerFilters: { level: "", source: "", query: "" },
      teamActiveTab: "agents",
      settingsActiveTab: "llm",
      homeCategory: "unity",
      lastProjectId: null,
      ioViewerWidth: 380,
      scaffoldParent: null,

      setInceptionLlm: (v) => set({ inceptionLlm: v }),
      setInceptionModel: (v) => set({ inceptionModel: v }),
      setLogDrawerExpanded: (v) => set({ logDrawerExpanded: v }),
      setLogDrawerActiveTab: (v) => set({ logDrawerActiveTab: v }),
      // Clamp 120..600px — below 120 nothing's visible, above 600 the
      // page above is cramped on small windows.
      setLogDrawerHeight: (v) => set({
        logDrawerHeight: Math.min(600, Math.max(120, Math.round(v))),
      }),
      setLogDrawerFilters: (patch) => set((s) => ({
        logDrawerFilters: { ...s.logDrawerFilters, ...patch },
      })),
      setTeamActiveTab: (v) => set({ teamActiveTab: v }),
      setSettingsActiveTab: (v) => set({ settingsActiveTab: v }),
      setHomeCategory: (v) => set({ homeCategory: v }),
      setLastProjectId: (v) => set({ lastProjectId: v }),
      // Clamp 280-1200 — below 280 the JSON tree becomes unreadable;
      // above 1200 the canvas behind gets squeezed off-screen.
      setIoViewerWidth: (v) => set({
        ioViewerWidth: Math.min(1200, Math.max(280, Math.round(v))),
      }),
      setScaffoldParent: (v) => set({ scaffoldParent: v }),
    }),
    {
      name: "mycrew-prefs",
      version: 3,
      // v1 → v2: 「应用日志」 tab renamed to 「后端日志」 + new
      // logDrawerHeight / logDrawerFilters fields. Old persisted state
      // may have any of these missing or with the old tab label.
      // v2 → v3: added homeCategory toggle (Unity / AI 视频 / PPT 视频).
      migrate: (persisted: any, _from) => {
        if (!persisted || typeof persisted !== "object") return persisted;
        if (persisted.logDrawerActiveTab === "应用日志") {
          persisted.logDrawerActiveTab = "后端日志";
        }
        if (typeof persisted.logDrawerHeight !== "number") {
          persisted.logDrawerHeight = 224;
        }
        if (!persisted.logDrawerFilters) {
          persisted.logDrawerFilters = { level: "", source: "", query: "" };
        }
        if (!persisted.homeCategory) {
          persisted.homeCategory = "unity";
        }
        return persisted;
      },
    },
  ),
);
