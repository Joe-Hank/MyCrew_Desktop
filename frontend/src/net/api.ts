const DEFAULT_PORT = 18321;

let backendPort = DEFAULT_PORT;

export function setBackendPort(port: number) {
  backendPort = port;
}

export function getBaseUrl(): string {
  return `http://127.0.0.1:${backendPort}/api/v1`;
}

export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<{ ok: boolean; data: T; error?: { code: string; message: string } }> {
  const url = `${getBaseUrl()}${path}`;
  const resp = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  return resp.json();
}
