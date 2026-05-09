import { useEffect, useState } from "react";
import { wsClient } from "../net/ws";
import { setBackendPort } from "../net/api";

const DEFAULT_PORT = 18321;

export function useBackendConnection() {
  const [connected, setConnected] = useState(false);
  const [port, setPort] = useState<number | null>(null);

  useEffect(() => {
    async function connect() {
      let p = DEFAULT_PORT;

      try {
        const { invoke } = await import("@tauri-apps/api/core");
        p = await invoke<number>("get_backend_port");
      } catch {
        // not in Tauri context or backend not ready, use default
      }

      setPort(p);
      setBackendPort(p);
      wsClient.connect(p);
    }

    connect();

    const offConnected = wsClient.on("ws.connected", () => setConnected(true));
    const offDisconnected = wsClient.on("ws.disconnected", () => setConnected(false));

    return () => {
      offConnected();
      offDisconnected();
      wsClient.disconnect();
    };
  }, []);

  return { connected, port };
}
