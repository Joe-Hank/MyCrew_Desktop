export interface WsMessage {
  type: string;
  ts: string;
  payload: Record<string, unknown>;
}

type Listener = (msg: WsMessage) => void;

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000];

class WsClient {
  private ws: WebSocket | null = null;
  private listeners = new Map<string, Set<Listener>>();
  private globalListeners = new Set<Listener>();
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private url = "";
  private closed = false;

  connect(port: number) {
    this.url = `ws://127.0.0.1:${port}/api/v1/ws`;
    this.closed = false;
    this.doConnect();
  }

  disconnect() {
    this.closed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  on(eventType: string, listener: Listener): () => void {
    let set = this.listeners.get(eventType);
    if (!set) {
      set = new Set();
      this.listeners.set(eventType, set);
    }
    set.add(listener);
    return () => set!.delete(listener);
  }

  onAny(listener: Listener): () => void {
    this.globalListeners.add(listener);
    return () => this.globalListeners.delete(listener);
  }

  send(type: string, payload: Record<string, unknown> = {}) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, payload }));
    }
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private doConnect() {
    if (this.closed || !this.url) return;

    // CRITICAL: close + detach any prior socket before opening a new one.
    // Without this, every reconnect / re-discovery accumulates a "ghost"
    // WebSocket whose onmessage handler is still bound to the same
    // listener set → backend broadcasts get dispatched N times where N =
    // number of ghosts. Symptoms: duplicated pm.log entries, duplicated
    // sub_agent_io lines, etc.
    if (this.ws) {
      const stale = this.ws;
      stale.onopen = null;
      stale.onmessage = null;
      stale.onclose = null;
      stale.onerror = null;
      try { stale.close(); } catch { /* ignore */ }
      this.ws = null;
    }

    let socket: WebSocket;
    try {
      socket = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      // Guard against a stale socket whose onopen fires after we've
      // already replaced this.ws — only the current socket should
      // emit a "ws.connected" event and reset reconnect attempts.
      if (this.ws !== socket) return;
      this.reconnectAttempt = 0;
      this.dispatch({ type: "ws.connected", ts: new Date().toISOString(), payload: {} });
    };

    socket.onmessage = (ev) => {
      if (this.ws !== socket) return;  // ignore late frames from a stale ws
      try {
        const msg: WsMessage = JSON.parse(ev.data);
        this.dispatch(msg);
      } catch {
        // ignore malformed messages
      }
    };

    socket.onclose = () => {
      // Only the CURRENT socket's close should trigger a reconnect. A
      // detached ghost socket closing must not schedule a new connection
      // (that's how the cascading reconnect / ghost-accumulation loop
      // got going in the first place).
      if (this.ws !== socket) return;
      this.dispatch({ type: "ws.disconnected", ts: new Date().toISOString(), payload: {} });
      this.scheduleReconnect();
    };

    socket.onerror = () => {
      // onclose will fire after onerror
    };
  }

  private dispatch(msg: WsMessage) {
    const typeListeners = this.listeners.get(msg.type);
    if (typeListeners) {
      for (const fn of typeListeners) fn(msg);
    }
    for (const fn of this.globalListeners) fn(msg);
  }

  private scheduleReconnect() {
    if (this.closed) return;
    const delay = RECONNECT_DELAYS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS.length - 1)];
    this.reconnectAttempt++;
    this.reconnectTimer = setTimeout(() => this.doConnect(), delay);
  }
}

export const wsClient = new WsClient();
