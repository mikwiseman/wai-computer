export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(status: number, message: string, payload: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

const DEFAULT_BASE_URL = "";
const LOCALHOST_ACCESS_COOKIE_NAME = "wai_access_token";
const LOCALHOST_REFRESH_COOKIE_NAME = "wai_refresh_token";

export function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_BASE_URL;
}

export function isLocalhostBrowser(): boolean {
  if (typeof window === "undefined" || typeof document === "undefined") {
    return false;
  }

  return window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
}

export function syncLocalhostAuthCookie(token: string | null): void {
  if (!isLocalhostBrowser()) {
    return;
  }

  if (!token) {
    document.cookie = `${LOCALHOST_ACCESS_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
    return;
  }

  document.cookie = `${LOCALHOST_ACCESS_COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; SameSite=Lax`;
}

export function syncLocalhostRefreshCookie(token: string | null): void {
  if (!isLocalhostBrowser()) {
    return;
  }

  if (!token) {
    document.cookie = `${LOCALHOST_REFRESH_COOKIE_NAME}=; Path=/; Max-Age=0; SameSite=Lax`;
    return;
  }

  document.cookie = `${LOCALHOST_REFRESH_COOKIE_NAME}=${encodeURIComponent(token)}; Path=/; SameSite=Lax`;
}

async function parseResponsePayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text.trim().length === 0) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return text;
    }
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function buildMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object") {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
  }
  return fallback;
}

async function doFetch(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    throw new ApiError(
      0,
      "Network error — check your connection",
      { detail: String(error) },
    );
  }
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = `${getApiBaseUrl()}${path}`;
  const fetchInit: RequestInit = {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    credentials: "include",
    cache: "no-store",
  };

  let response = await doFetch(url, fetchInit);

  // On 401, attempt a single token refresh then retry
  if (response.status === 401) {
    try {
      const refreshResponse = await doFetch(`${getApiBaseUrl()}/api/auth/refresh`, {
        method: "POST",
        credentials: "include",
        cache: "no-store",
      });

      if (refreshResponse.ok) {
        // Extract new token and sync localhost cookie so the retry uses it
        const refreshPayload = await parseResponsePayload(refreshResponse);
        if (
          refreshPayload &&
          typeof refreshPayload === "object" &&
          typeof (refreshPayload as { access_token?: unknown }).access_token === "string"
        ) {
          syncLocalhostAuthCookie(
            (refreshPayload as { access_token: string }).access_token,
          );
        }
        if (
          refreshPayload &&
          typeof refreshPayload === "object" &&
          typeof (refreshPayload as { refresh_token?: unknown }).refresh_token === "string"
        ) {
          syncLocalhostRefreshCookie(
            (refreshPayload as { refresh_token: string }).refresh_token,
          );
        }
        response = await doFetch(url, fetchInit);
      }
    } catch {
      // Refresh failed (e.g. network error) — fall through to the original 401
    }
  }

  const payload = await parseResponsePayload(response);

  if (!response.ok) {
    throw new ApiError(response.status, buildMessage(payload, "API request failed"), payload);
  }

  return payload as T;
}
