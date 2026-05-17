/**
 * 桩：IoViewerDrawer 宽度持久化 + ESC 关闭 + sub-step IO 路由。
 *
 * Why this spec exists
 * --------------------
 * The IO drawer is the only way users inspect what an agent actually
 * received and produced. Three behaviours have been broken at least
 * once before:
 *
 *   1. **Width persistence.** Users drag the left edge to widen; the
 *      width is stored in usePrefsStore.ioViewerWidth so re-opens
 *      land at the same size. A regression silently reverts everyone
 *      to the default 480px.
 *   2. **ESC closes.** Pressing Escape calls onClose. If a sibling
 *      modal traps focus, this can quietly stop working.
 *   3. **sub-step IO routing.** When `stepIndex` is provided, the
 *      drawer reads the Crew sub-step's IO (via useSubIO) instead of
 *      the parent task's (useTaskIO). The raw_in / raw_out split was
 *      added 2026-05-17 to fix "input tab showing output's raw" — must
 *      not regress.
 *   4. **contract tab.** Reads `task.code_contract` synchronously, no
 *      fetch. Switching to contract tab should NOT trigger useTaskIO
 *      / useSubIO.
 *
 * Suggested approach
 * ------------------
 * Mock `../../queries/useWorkflowQuery` (useTaskIO, useSubIO) to
 * return controllable data, mock usePrefsStore to capture setter
 * calls. Then render with a fake `task` and assert.
 *
 * Stubs only.
 */
import { describe, it } from "vitest";
// import { render, screen, fireEvent } from "@testing-library/react";
// import IoViewerDrawer from "../IoViewerDrawer";

describe("IoViewerDrawer · width persistence", () => {
  it.todo("reads initial width from usePrefsStore.ioViewerWidth");
  it.todo("drag handle calls setIoViewerWidth as the user drags");
  it.todo("width persists across remounts (store value, not local state)");
  it.todo("width respects min/max clamp (no negative, no full-window)");
});

describe("IoViewerDrawer · ESC closes", () => {
  it.todo("pressing Escape calls onClose");
  it.todo("Escape only closes when the drawer has focus / is open");
});

describe("IoViewerDrawer · sub-step IO routing", () => {
  it.todo("stepIndex provided → uses useSubIO, not useTaskIO");
  it.todo("stepIndex undefined → uses useTaskIO, not useSubIO");
  it.todo("input tab reads subIo.raw_in (not raw_out)");
  it.todo("output tab reads subIo.raw_out (falls back to subIo.raw for legacy rows)");
});

describe("IoViewerDrawer · contract tab", () => {
  it.todo("contract tab renders task.code_contract synchronously");
  it.todo("contract tab does NOT trigger useTaskIO fetch");
  it.todo("contract tab does NOT trigger useSubIO fetch");
});
