/**
 * 桩：useBackendConnection 端口扫描 + WS 断线重连 + 鉴权锁。
 *
 * Why this spec exists
 * --------------------
 * useBackendConnection is the front-door for every page in the app.
 * It (a) discovers which port the Python sidecar bound to, (b) keeps
 * a WS connection open, and (c) handles the "auth-locked" breaker
 * that kicks in after ≥3 consecutive 4401 rejections.
 *
 * The breaker logic is famously easy to break — see the comment block
 * at the top of useBackendConnection.ts about `authLockedRef` being a
 * synchronous mirror because `useState` lags the disconnected handler
 * by one render. If that ref-mirror regresses, the app loops forever
 * between "locked" and "reconnecting".
 *
 * Behaviour worth pinning
 * -----------------------
 *   1. Port discovery prefers Tauri's `get_backend_port` invoke when
 *      available, falls back to sweeping 18321..18399.
 *   2. The currently-known port is probed first to avoid the full sweep.
 *   3. WS disconnect triggers an auto-reconnect timer — UNLESS auth is
 *      locked, in which case the user must click "重试".
 *   4. retryAuth() (via wsClient) clears the breaker and re-attempts.
 *
 * Suggested approach
 * ------------------
 * Mock `../net/api` (probeHealth, getBackendPort, setBackendPort) and
 * `../net/ws` (wsClient with .on / .connect / .retryAuth). Then
 * renderHook and assert call sequences with fake timers.
 *
 * Stubs only.
 */
import { describe, it } from "vitest";
// import { renderHook, act } from "@testing-library/react";
// import { useBackendConnection } from "../useBackendConnection";

describe("useBackendConnection · port discovery", () => {
  it.todo("uses Tauri invoke when available");
  it.todo("probes the last-known port first when Tauri invoke is absent");
  it.todo("sweeps 18321..18399 when no port is known");
  it.todo("emits connected=false when sweep finds nothing");
});

describe("useBackendConnection · WS disconnect recovery", () => {
  it.todo("schedules a reconnect after ws.disconnected event");
  it.todo("does NOT schedule reconnect when authLocked is true (synchronous guard via ref)");
  it.todo("clears reconnect timer when the component unmounts");
});

describe("useBackendConnection · auth-locked breaker", () => {
  it.todo("authLocked flips true on ws.auth_locked event");
  it.todo("authLocked flips false after wsClient.retryAuth() succeeds");
  it.todo("retryAuth path re-runs port discovery");
});

describe("useBackendConnection · query client invalidation", () => {
  it.todo("invalidates queries on (re)connect so stale data refreshes");
});
