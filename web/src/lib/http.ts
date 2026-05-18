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

function syncLocalhostAuthCookiesFromPayload(payload: unknown): void {
  if (!payload || typeof payload !== "object") {
    return;
  }

  if (typeof (payload as { access_token?: unknown }).access_token === "string") {
    syncLocalhostAuthCookie((payload as { access_token: string }).access_token);
  }

  if (typeof (payload as { refresh_token?: unknown }).refresh_token === "string") {
    syncLocalhostRefreshCookie((payload as { refresh_token: string }).refresh_token);
  }
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

function defaultMessageForStatus(status: number, fallback: string): string {
  if (status === 0) return "Network error — check your connection";
  if (status === 401) return "Your session ended. Please sign in again.";
  return fallback;
}

function shouldHideTechnicalMessage(message: string): boolean {
  const normalized = message.trim().toLowerCase();
  if (!normalized) return true;

  const technicalFragments = [
    "internal server error",
    "failed to reconnect after",
    "connection lost after retrying",
    "failed to get transcription token",
    "elevenlabs_api_key",
    "no elevenlabs model configured",
    "multiple elevenlabs models found",
    "nsurlerrordomain",
    "cfnetwork",
    "application support/",
    "/users/",
    "pendingtranscripts",
    "socket",
    "timed out",
  ];

  return technicalFragments.some((fragment) => normalized.includes(fragment)) || normalized.length > 180;
}

function buildMessage(payload: unknown, fallback: string, status: number): string {
  if (status >= 500) {
    return defaultMessageForStatus(status, fallback);
  }
  if (payload && typeof payload === "object") {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.length > 0) {
      return shouldHideTechnicalMessage(detail)
        ? defaultMessageForStatus(status, fallback)
        : detail;
    }
  }
  return defaultMessageForStatus(status, fallback);
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

export async function tryRefreshAuthSession(): Promise<boolean> {
  const refreshResponse = await doFetch(`${getApiBaseUrl()}/api/auth/refresh`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
  });

  if (!refreshResponse.ok) {
    return false;
  }

  const refreshPayload = await parseResponsePayload(refreshResponse);
  syncLocalhostAuthCookiesFromPayload(refreshPayload);
  return true;
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
      if (await tryRefreshAuthSession()) {
        response = await doFetch(url, fetchInit);
      }
    } catch {
      // Refresh failed (e.g. network error) — fall through to the original 401
    }
  }

  const payload = await parseResponsePayload(response);

  if (!response.ok) {
    throw new ApiError(
      response.status,
      buildMessage(payload, "Something went wrong. Please try again in a moment.", response.status),
      payload,
    );
  }

  return payload as T;
}

/**
 * Like apiFetch but returns the raw Response (for non-JSON responses like text/blob exports).
 * Includes the same 401 auto-refresh-and-retry logic.
 */
export async function apiFetchResponse(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const url = `${getApiBaseUrl()}${path}`;
  const fetchInit: RequestInit = {
    ...init,
    credentials: "include",
    cache: "no-store",
  };

  let response = await doFetch(url, fetchInit);

  if (response.status === 401) {
    try {
      if (await tryRefreshAuthSession()) {
        response = await doFetch(url, fetchInit);
      }
    } catch {
      // Refresh failed — fall through to original response
    }
  }

  if (!response.ok) {
    const payload = await parseResponsePayload(response);
    throw new ApiError(
      response.status,
      buildMessage(payload, "Something went wrong. Please try again in a moment.", response.status),
      payload,
    );
  }

  return response;
}

/**
 * Upload a file via multipart/form-data. Browser sets Content-Type + boundary automatically.
 * Includes 401 auto-refresh-and-retry.
 */
export async function apiUpload<T>(
  path: string,
  formData: FormData,
): Promise<T> {
  const url = `${getApiBaseUrl()}${path}`;
  const fetchInit: RequestInit = {
    method: "POST",
    body: formData,
    credentials: "include",
    cache: "no-store",
  };

  let response = await doFetch(url, fetchInit);

  if (response.status === 401) {
    try {
      if (await tryRefreshAuthSession()) {
        response = await doFetch(url, fetchInit);
      }
    } catch {
      // Refresh failed
    }
  }

  const payload = await parseResponsePayload(response);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      buildMessage(payload, "Upload failed. Please try again.", response.status),
      payload,
    );
  }
  return payload as T;
}
