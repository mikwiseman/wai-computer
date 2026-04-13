import {
  apiFetch,
  apiFetchResponse,
  apiUpload,
  syncLocalhostAuthCookie,
  syncLocalhostRefreshCookie,
} from "./http";
import type {
  ActionItem,
  ActionPriority,
  ActionStatus,
  AnalyticsResponse,
  BulkAction,
  BulkOperationResponse,
  Entity,
  EntityDetail,
  EntityType,
  ExportFormat,
  KeywordsResponse,
  MessageResponse,
  StarRecordingResponse,
  QAResponse,
  Recording,
  RecordingDetail,
  RecordingType,
  RealtimeVoiceMode,
  RealtimeVoiceSession,
  RelatedRecordingsResponse,
  SearchResponse,
  SpeakerStatsResponse,
  Summary,
  TokenResponse,
  TranscriptSearchResponse,
  TranscriptStatsResponse,
  User,
  UserSettings,
  WeeklyDigestResponse,
} from "./types";

function asQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

async function withLocalhostAuth<T extends TokenResponse>(promise: Promise<T>): Promise<T> {
  const response = await promise;
  if (typeof response.access_token === "string" && response.access_token.length > 0) {
    syncLocalhostAuthCookie(response.access_token);
  }
  if (typeof response.refresh_token === "string" && response.refresh_token.length > 0) {
    syncLocalhostRefreshCookie(response.refresh_token);
  }
  return response;
}

export function register(email: string, password: string): Promise<TokenResponse> {
  return withLocalhostAuth(
    apiFetch<TokenResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  );
}

export function login(email: string, password: string): Promise<TokenResponse> {
  return withLocalhostAuth(
    apiFetch<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  );
}

export function requestMagicLink(email: string): Promise<MessageResponse> {
  return apiFetch<MessageResponse>("/api/auth/magic-link", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function verifyMagicLink(token: string): Promise<TokenResponse> {
  return withLocalhostAuth(
    apiFetch<TokenResponse>("/api/auth/verify-magic", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  );
}

export function refreshToken(): Promise<TokenResponse> {
  return withLocalhostAuth(apiFetch<TokenResponse>("/api/auth/refresh", { method: "POST" }));
}

export async function logout(): Promise<MessageResponse> {
  const response = await apiFetch<MessageResponse>("/api/auth/logout", { method: "POST" });
  syncLocalhostAuthCookie(null);
  syncLocalhostRefreshCookie(null);
  return response;
}

export function getCurrentUser(): Promise<User> {
  return apiFetch<User>("/api/auth/me");
}

export function listRecordings(params?: {
  skip?: number;
  limit?: number;
  type?: RecordingType;
}): Promise<Recording[]> {
  return apiFetch<Recording[]>(
    `/api/recordings${asQuery({
      skip: params?.skip,
      limit: params?.limit,
      type: params?.type,
    })}`,
  );
}

export function createRecording(input: {
  title?: string | null;
  type?: RecordingType;
  language?: string;
}): Promise<Recording> {
  return apiFetch<Recording>("/api/recordings", {
    method: "POST",
    body: JSON.stringify({
      title: input.title ?? null,
      type: input.type ?? "note",
      language: input.language ?? "multi",
    }),
  });
}

export function getRecording(recordingId: string): Promise<RecordingDetail> {
  return apiFetch<RecordingDetail>(`/api/recordings/${recordingId}`);
}

export function updateRecording(
  recordingId: string,
  input: { title?: string | null; type?: RecordingType },
): Promise<Recording> {
  return apiFetch<Recording>(`/api/recordings/${recordingId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteRecording(recordingId: string): Promise<void> {
  return apiFetch<void>(`/api/recordings/${recordingId}`, { method: "DELETE" });
}

export function uploadAudio(recordingId: string, file: File): Promise<RecordingDetail> {
  const formData = new FormData();
  formData.append("file", file);
  return apiUpload<RecordingDetail>(`/api/recordings/${recordingId}/upload`, formData);
}

export function bulkRecordingOperation(
  recordingIds: string[],
  action: BulkAction,
  folderId?: string | null,
): Promise<BulkOperationResponse> {
  return apiFetch<BulkOperationResponse>("/api/recordings/bulk", {
    method: "POST",
    body: JSON.stringify({
      recording_ids: recordingIds,
      action,
      folder_id: folderId,
    }),
  });
}

export function starRecording(recordingId: string): Promise<StarRecordingResponse> {
  return apiFetch<StarRecordingResponse>(`/api/recordings/${recordingId}/star`, {
    method: "POST",
  });
}

export function unstarRecording(recordingId: string): Promise<StarRecordingResponse> {
  return apiFetch<StarRecordingResponse>(`/api/recordings/${recordingId}/star`, {
    method: "DELETE",
  });
}

export function getSpeakerStats(recordingId: string): Promise<SpeakerStatsResponse> {
  return apiFetch<SpeakerStatsResponse>(`/api/recordings/${recordingId}/speaker-stats`);
}

export function searchTranscript(
  recordingId: string,
  query: string,
  limit?: number,
): Promise<TranscriptSearchResponse> {
  return apiFetch<TranscriptSearchResponse>(
    `/api/recordings/${recordingId}/transcript/search${asQuery({ q: query, limit })}`,
  );
}

export function getTranscriptStats(recordingId: string): Promise<TranscriptStatsResponse> {
  return apiFetch<TranscriptStatsResponse>(`/api/recordings/${recordingId}/transcript-stats`);
}

export function getRecordingKeywords(
  recordingId: string,
  limit?: number,
): Promise<KeywordsResponse> {
  return apiFetch<KeywordsResponse>(
    `/api/recordings/${recordingId}/keywords${asQuery({ limit })}`,
  );
}

export function getRelatedRecordings(
  recordingId: string,
  limit?: number,
): Promise<RelatedRecordingsResponse> {
  return apiFetch<RelatedRecordingsResponse>(
    `/api/recordings/${recordingId}/related${asQuery({ limit })}`,
  );
}

export function getSummary(recordingId: string): Promise<Summary> {
  return apiFetch<Summary>(`/api/recordings/${recordingId}/summary`);
}

export function generateSummary(recordingId: string): Promise<Summary> {
  return apiFetch<Summary>(`/api/recordings/${recordingId}/generate-summary`, {
    method: "POST",
  });
}

export function search(params: { q: string; limit?: number; offset?: number }): Promise<SearchResponse> {
  return apiFetch<SearchResponse>(`/api/search${asQuery(params)}`);
}

export function semanticSearch(params: {
  q: string;
  limit?: number;
  threshold?: number;
}): Promise<SearchResponse> {
  return apiFetch<SearchResponse>(`/api/search/semantic${asQuery(params)}`);
}

export function fulltextSearch(params: {
  q: string;
  limit?: number;
  offset?: number;
}): Promise<SearchResponse> {
  return apiFetch<SearchResponse>(`/api/search/fts${asQuery(params)}`);
}

export function listActionItems(params?: {
  status?: ActionStatus;
  priority?: ActionPriority;
  limit?: number;
  offset?: number;
}): Promise<ActionItem[]> {
  return apiFetch<ActionItem[]>(`/api/action-items${asQuery(params || {})}`);
}

export function updateActionItem(
  itemId: string,
  payload: Partial<{
    task: string | null;
    owner: string | null;
    due_date: string | null;
    priority: ActionPriority | null;
    status: ActionStatus | null;
  }>,
): Promise<ActionItem> {
  return apiFetch<ActionItem>(`/api/action-items/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteActionItem(itemId: string): Promise<void> {
  return apiFetch<void>(`/api/action-items/${itemId}`, {
    method: "DELETE",
  });
}

export function listEntities(type?: EntityType): Promise<Entity[]> {
  return apiFetch<Entity[]>(`/api/entities${asQuery({ type })}`);
}

export function getEntity(entityId: string): Promise<EntityDetail> {
  return apiFetch<EntityDetail>(`/api/entities/${entityId}`);
}

export function createEntity(payload: {
  type: EntityType;
  name: string;
  metadata?: Record<string, unknown>;
}): Promise<Entity> {
  return apiFetch<Entity>("/api/entities", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteEntity(entityId: string): Promise<void> {
  return apiFetch<void>(`/api/entities/${entityId}`, { method: "DELETE" });
}

export function changePassword(currentPassword: string, newPassword: string): Promise<MessageResponse> {
  return apiFetch<MessageResponse>("/api/settings/change-password", {
    method: "POST",
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

export function getSettings(): Promise<UserSettings> {
  return apiFetch<UserSettings>("/api/settings");
}

export function updateSettings(settings: Partial<UserSettings>): Promise<UserSettings> {
  return apiFetch<UserSettings>("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(settings),
  });
}

export function askDatabase(payload: {
  question: string;
  recording_ids?: string[] | null;
}): Promise<QAResponse> {
  return apiFetch<QAResponse>('/api/qa', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}


export function getWeeklyDigest(): Promise<WeeklyDigestResponse> {
  return apiFetch<WeeklyDigestResponse>("/api/recordings/digest/weekly");
}

export function getRecordingAnalytics(): Promise<AnalyticsResponse> {
  return apiFetch<AnalyticsResponse>("/api/recordings/analytics");
}

export async function exportRecording(recordingId: string, format: ExportFormat): Promise<Blob> {
  const response = await apiFetchResponse(
    `/api/recordings/${recordingId}/export?format=${format}`,
  );
  return response.blob();
}


