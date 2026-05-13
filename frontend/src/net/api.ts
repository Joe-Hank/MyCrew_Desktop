const DEFAULT_PORT = 18321;
const DEFAULT_TIMEOUT_MS = 8_000;

let backendPort = DEFAULT_PORT;

export function setBackendPort(port: number) {
  backendPort = port;
}

export function getBackendPort(): number {
  return backendPort;
}

export function getBaseUrl(): string {
  return `http://127.0.0.1:${backendPort}/api/v1`;
}

export class ApiError extends Error {
  readonly kind: "network" | "timeout" | "http" | "envelope" | "parse";
  readonly status?: number;
  readonly code?: string;
  constructor(
    kind: ApiError["kind"],
    message: string,
    extra?: { status?: number; code?: string; cause?: unknown },
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = extra?.status;
    this.code = extra?.code;
    if (extra?.cause) (this as { cause?: unknown }).cause = extra.cause;
  }
}

export interface ApiEnvelope<T> {
  ok: boolean;
  data: T;
  error?: { code: string; message: string };
}

/**
 * Calls the backend and returns the parsed envelope. Throws ApiError on:
 *   - network failure / backend down
 *   - request timeout
 *   - non-2xx HTTP status
 *   - non-JSON or malformed body
 *   - envelope with ok=false
 *
 * Callers should rely on React Query's isError to surface failures rather
 * than treating an empty data array as "no records".
 */
export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit & { timeoutMs?: number },
): Promise<ApiEnvelope<T>> {
  const url = `${getBaseUrl()}${path}`;
  // Pass `timeoutMs: 0` (or any non-positive) to opt out — needed for
  // long-running LLM endpoints (Plan Maker can take 60-120s).
  const timeoutMs = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const externalSignal = init?.signal ?? undefined;

  // Compose external (user-Stop) + internal (timeout) into one controller.
  // The previous version set `signal: controller.signal` AFTER `...init`,
  // which silently shadowed the caller's signal — so the chat-queue Stop
  // button never actually aborted the fetch.
  const controller = new AbortController();
  let timedOut = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  if (timeoutMs > 0 && Number.isFinite(timeoutMs)) {
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }
  const onExternalAbort = externalSignal
    ? () => controller.abort()
    : null;
  if (externalSignal && onExternalAbort) {
    if (externalSignal.aborted) {
      onExternalAbort();
    } else {
      externalSignal.addEventListener("abort", onExternalAbort);
    }
  }

  const cleanup = () => {
    if (timer) clearTimeout(timer);
    if (externalSignal && onExternalAbort) {
      externalSignal.removeEventListener("abort", onExternalAbort);
    }
  };

  let resp: Response;
  try {
    resp = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
  } catch (err) {
    cleanup();
    if (timedOut) {
      throw new ApiError("timeout", `请求超时（${timeoutMs}ms）: ${path}`, { cause: err });
    }
    if (externalSignal?.aborted) {
      // Re-throw as a real AbortError so the chat queue's `err.name ===
      // 'AbortError'` branch fires and the Stop button stays "Stop-shaped"
      // rather than surfacing the failure to the user as a generic error.
      const aborted = new Error("aborted");
      (aborted as Error & { name: string }).name = "AbortError";
      throw aborted;
    }
    throw new ApiError("network", `后端未连接或不可达: ${path}`, { cause: err });
  }
  cleanup();

  const raw = await resp.text();
  if (!resp.ok) {
    throw new ApiError("http", `HTTP ${resp.status} ${path}: ${raw.slice(0, 200)}`, {
      status: resp.status,
    });
  }

  let body: ApiEnvelope<T>;
  try {
    body = raw ? (JSON.parse(raw) as ApiEnvelope<T>) : ({ ok: true, data: undefined as unknown as T });
  } catch (err) {
    throw new ApiError("parse", `响应不是合法 JSON: ${raw.slice(0, 200)}`, { cause: err });
  }

  if (body && body.ok === false) {
    throw new ApiError("envelope", body.error?.message ?? "服务端返回 ok=false", {
      code: body.error?.code,
    });
  }
  return body;
}

/**
 * Probe http://127.0.0.1:<port>/api/v1/health with a short timeout.
 * Returns true if the backend answers ok. Used by port discovery.
 */
export async function probeHealth(port: number, timeoutMs = 800): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const r = await fetch(`http://127.0.0.1:${port}/api/v1/health`, {
      signal: controller.signal,
    });
    if (!r.ok) return false;
    const j = (await r.json()) as { ok?: boolean };
    return !!j?.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
