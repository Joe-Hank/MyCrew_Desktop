import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { wsClient } from "../net/ws";
import { setBackendPort, getBackendPort, probeHealth } from "../net/api";

const DEFAULT_PORT = 18321;
// Mirrors backend/bootstrap/paths.py PORT_RANGE = range(18321, 18400)
const PROBE_PORTS: number[] = Array.from({ length: 79 }, (_, i) => 18321 + i);
const PROBE_INTERVAL_MS = 3_000;

async function discoverPort(): Promise<number | null> {
  // Tauri sidecar wins if available
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const p = await invoke<number>("get_backend_port");
    if (typeof p === "number" && p > 0) return p;
  } catch {
    // not in Tauri context
  }

  // Probe the current port first to avoid waste, then sweep the range
  const current = getBackendPort();
  const ordered = [current, ...PROBE_PORTS.filter((p) => p !== current)];
  for (const p of ordered) {
    if (await probeHealth(p)) return p;
  }
  return null;
}

export function useBackendConnection() {
  const [connected, setConnected] = useState(false);
  const [port, setPort] = useState<number | null>(null);
  // True once the WS layer has tripped its auth-failure breaker (≥3
  // consecutive 4401 rejections). AppShell renders a dedicated banner
  // with a 「重试」 button → wsClient.retryAuth() clears the breaker.
  const [authLocked, setAuthLocked] = useState(false);
  const qc = useQueryClient();

  useEffect(() => {
    let cancelled = false;
    let probeTimer: ReturnType<typeof setTimeout> | null = null;

    async function tryConnect(reason: string) {
      if (cancelled) return;
      const found = await discoverPort();
      if (cancelled) return;

      if (found != null) {
        setPort(found);
        setBackendPort(found);
        wsClient.connect(found);
        // After a (re)connect, the cached queries may be stale or marked as
        // error. Force them to refetch so the UI snaps back without a manual
        // refresh — root cause of repeated "data disappeared" reports.
        if (reason !== "initial") qc.invalidateQueries();
      } else {
        // No backend reachable yet — fall back to default port for the URL,
        // schedule another sweep, and let the WS reconnector keep trying too.
        setBackendPort(DEFAULT_PORT);
        wsClient.connect(DEFAULT_PORT);
        probeTimer = setTimeout(() => tryConnect("retry"), PROBE_INTERVAL_MS);
      }
    }

    tryConnect("initial");

    const offConnected = wsClient.on("ws.connected", () => {
      setConnected(true);
      setAuthLocked(false);
    });
    const offDisconnected = wsClient.on("ws.disconnected", () => {
      setConnected(false);
      // WS dropped — backend may have died or moved to another port. Schedule
      // a fresh port discovery on top of WS's own backoff.
      if (probeTimer) clearTimeout(probeTimer);
      probeTimer = setTimeout(() => tryConnect("ws-down"), PROBE_INTERVAL_MS);
    });
    const offAuthLocked = wsClient.on("ws.auth_locked", () => {
      setAuthLocked(true);
    });

    return () => {
      cancelled = true;
      if (probeTimer) clearTimeout(probeTimer);
      offConnected();
      offDisconnected();
      offAuthLocked();
      wsClient.disconnect();
    };
  }, [qc]);

  const retryAuth = () => {
    setAuthLocked(false);
    wsClient.retryAuth();
  };

  return { connected, port, authLocked, retryAuth };
}
