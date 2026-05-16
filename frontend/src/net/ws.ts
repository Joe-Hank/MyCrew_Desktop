export interface WsMessage {
  type: string;
  ts: string;
  payload: Record<string, unknown>;
}

type Listener = (msg: WsMessage) => void;

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000];

// Auth circuit breaker — after this many consecutive 4401 rejections,
// stop reconnecting and emit `ws.auth_locked`. AppShell catches the
// event and shows a banner with a 「重试」 button that calls retryAuth().
// Three is enough to weather a transient backend reload (token rotates
// → 1-2 rejected attempts → fetchToken pulls fresh → success) without
// burning the user's log with hundreds of warnings when something is
// truly stuck (e.g. multiple frontend tabs racing on token rotation,
// or a backend/proxy mismatch on the auth endpoint).
const MAX_AUTH_FAILURES = 3;

class WsClient {
  private ws: WebSocket | null = null;
  private listeners = new Map<string, Set<Listener>>();
  private globalListeners = new Set<Listener>();
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  // Base URL stays free of the token so reconnects re-fetch fresh
  // (e.g. if the backend restarts between attempts and rotates the
  // session token).
  private baseUrl = "";
  private port = 0;
  private token = "";
  private closed = false;
  private authFailures = 0;
  private authLocked = false;

  connect(port: number) {
    this.port = port;
    this.baseUrl = `ws://127.0.0.1:${port}/api/v1/ws`;
    this.closed = false;
    // A fresh connect() (e.g. AppShell remounted, port re-discovered)
    // is the user's implicit intent to try again — unlock the auth
    // breaker too.
    this.authFailures = 0;
    this.authLocked = false;
    this.doConnect();
  }

  /** Manual unlock for the AppShell banner's 「重试」 button.
   *  Resets the auth-failure counter, clears the closed flag, and
   *  triggers an immediate reconnect attempt. Idempotent: a no-op when
   *  the breaker isn't tripped. */
  retryAuth() {
    if (!this.authLocked) return;
    this.authFailures = 0;
    this.authLocked = false;
    this.closed = false;
    this.token = "";  // force fetchToken on the next attempt
    this.doConnect();
  }

  /** Fetch the WS session token from the backend's localhost-only
   *  auth endpoint. The backend rotates this token on every boot so
   *  the previous one is meaningless after a restart — we always
   *  refresh before opening a fresh socket. Returns the token or
   *  empty string on failure (callers schedule a reconnect). */
  private async fetchToken(): Promise<string> {
    try {
      const res = await fetch(`http://127.0.0.1:${this.port}/api/v1/auth/ws_token`);
      if (!res.ok) return "";
      const body = await res.json();
      return body?.data?.token ?? "";
    } catch {
      return "";
    }
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

  private async doConnect() {
    if (this.closed || !this.baseUrl) return;

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

    // Refresh the session token before each connect attempt — covers
    // backend restarts (token rotates) and the initial cold start.
    if (!this.token) {
      this.token = await this.fetchToken();
    }
    if (!this.token) {
      // Token endpoint not ready yet — back off and try again. The
      // backend lifespan generates the token early, so this only
      // happens during a very brief window at boot.
      this.scheduleReconnect();
      return;
    }
    const fullUrl = `${this.baseUrl}?token=${encodeURIComponent(this.token)}`;

    let socket: WebSocket;
    try {
      socket = new WebSocket(fullUrl);
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
      this.authFailures = 0;  // any successful open clears the breaker
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

    socket.onclose = (ev) => {
      // Only the CURRENT socket's close should trigger a reconnect. A
      // detached ghost socket closing must not schedule a new connection
      // (that's how the cascading reconnect / ghost-accumulation loop
      // got going in the first place).
      if (this.ws !== socket) return;
      // Code 4401 = backend rejected our token (e.g. backend restarted
      // and rotated the session token). Drop the cached value so the
      // next doConnect() refetches /auth/ws_token.
      if (ev.code === 4401) {
        this.token = "";
        this.authFailures++;
        if (this.authFailures >= MAX_AUTH_FAILURES) {
          // Trip the breaker: stop the reconnect loop + tell the UI
          // to show a banner. Without this the log fills with
          // ws.auth_rejected forever (one per ~5-15s backoff tick).
          this.authLocked = true;
          this.closed = true;
          this.dispatch({
            type: "ws.auth_locked",
            ts: new Date().toISOString(),
            payload: { failures: this.authFailures },
          });
          this.dispatch({
            type: "ws.disconnected",
            ts: new Date().toISOString(),
            payload: {},
          });
          return;
        }
      }
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
