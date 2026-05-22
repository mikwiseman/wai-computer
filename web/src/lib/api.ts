import {
  ApiError,
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
  ApiKey,
  ApiKeyCreated,
  BulkAction,
  BulkOperationResponse,
  DictationBenchmarkBattleResponse,
  DictationBenchmarkVoteResponse,
  Entity,
  EntityDetail,
  EntityType,
  ExportFormat,
  KeywordsResponse,
  McpConnection,
  MessageResponse,
  Person,
  StarRecordingResponse,
  VoiceEnrollmentResponse,
  Recording,
  RecordingDetail,
  RecordingType,
  RelatedRecordingsResponse,
  RecordingShareLink,
  SearchResponse,
  SpeakerStatsResponse,
  SharedRecording,
  Summary,
  TelegramLinkStatus,
  TelegramPairing,
  TokenResponse,
  TranscriptionOptions,
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
  if (
    (!("access_token" in response) || typeof response.access_token !== "string")
    && "message" in response
    && typeof (response as { message?: unknown }).message === "string"
  ) {
    throw new ApiError(200, (response as { message: string }).message, response);
  }
  if (typeof response.access_token === "string" && response.access_token.length > 0) {
    syncLocalhostAuthCookie(response.access_token);
  }
  if (typeof response.refresh_token === "string" && response.refresh_token.length > 0) {
    syncLocalhostRefreshCookie(response.refresh_token);
  }
  return response;
}

interface AuthLocaleOptions {
  locale?: "en" | "ru";
  region?: "global" | "ru";
}

export function register(
  email: string,
  password: string,
  options: AuthLocaleOptions = {},
): Promise<TokenResponse> {
  return withLocalhostAuth(
    apiFetch<TokenResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        ...(options.locale ? { locale: options.locale } : {}),
        ...(options.region ? { region: options.region } : {}),
      }),
    }),
  );
}

export function login(
  email: string,
  password: string,
  options: AuthLocaleOptions = {},
): Promise<TokenResponse> {
  return withLocalhostAuth(
    apiFetch<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        ...(options.locale ? { locale: options.locale } : {}),
        ...(options.region ? { region: options.region } : {}),
      }),
    }),
  );
}

export function requestMagicLink(
  email: string,
  options: AuthLocaleOptions = {},
): Promise<MessageResponse> {
  return apiFetch<MessageResponse>("/api/auth/magic-link", {
    method: "POST",
    body: JSON.stringify({
      email,
      ...(options.locale ? { locale: options.locale } : {}),
      ...(options.region ? { region: options.region } : {}),
    }),
  });
}

export function requestPasswordReset(
  email: string,
  locale: AuthLocaleOptions["locale"],
): Promise<MessageResponse> {
  return apiFetch<MessageResponse>("/api/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email, locale }),
  });
}

export function verifyMagicLink(
  token: string,
  options: Pick<AuthLocaleOptions, "locale"> = {},
): Promise<TokenResponse> {
  return withLocalhostAuth(
    apiFetch<TokenResponse>("/api/auth/verify-magic", {
      method: "POST",
      body: JSON.stringify({
        token,
        ...(options.locale ? { locale: options.locale } : {}),
      }),
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
  folder_id?: string | null;
  trashed?: boolean;
  starred?: boolean;
}): Promise<Recording[]> {
  return apiFetch<Recording[]>(
    `/api/recordings${asQuery({
      skip: params?.skip,
      limit: params?.limit,
      type: params?.type,
      folder_id: params?.folder_id,
      trashed: params?.trashed,
      starred: params?.starred,
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

export function deleteRecording(
  recordingId: string,
  options?: { permanent?: boolean },
): Promise<void> {
  return apiFetch<void>(
    `/api/recordings/${recordingId}${asQuery({ permanent: options?.permanent })}`,
    { method: "DELETE" },
  );
}

export function restoreRecording(recordingId: string): Promise<Recording> {
  return apiFetch<Recording>(`/api/recordings/${recordingId}/restore`, { method: "POST" });
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

export function listPeople(): Promise<Person[]> {
  return apiFetch<Person[]>("/api/people");
}

export function createPerson(input: {
  display_name: string;
  color?: string | null;
  aliases?: string[] | null;
}): Promise<Person> {
  return apiFetch<Person>("/api/people", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updatePerson(
  personId: string,
  input: { display_name?: string; color?: string | null; aliases?: string[] | null },
): Promise<Person> {
  return apiFetch<Person>(`/api/people/${personId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deletePerson(personId: string): Promise<void> {
  return apiFetch<void>(`/api/people/${personId}`, { method: "DELETE" });
}

export function mergePeople(sourceId: string, intoPersonId: string): Promise<Person> {
  return apiFetch<Person>(`/api/people/${sourceId}/merge`, {
    method: "POST",
    body: JSON.stringify({ into_person_id: intoPersonId }),
  });
}

export function assignSpeaker(
  recordingId: string,
  input:
    | { raw_label: string; person_id: string }
    | { raw_label: string; new_display_name: string },
): Promise<RecordingDetail> {
  return apiFetch<RecordingDetail>(`/api/recordings/${recordingId}/assign-speaker`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function enrollVoice(input: {
  audio: Blob;
  filename?: string;
  display_name?: string;
  person_id?: string;
}): Promise<VoiceEnrollmentResponse> {
  const formData = new FormData();
  formData.append("audio", input.audio, input.filename ?? "enrollment.wav");
  if (input.display_name) formData.append("display_name", input.display_name);
  if (input.person_id) formData.append("person_id", input.person_id);
  return apiUpload<VoiceEnrollmentResponse>("/api/voice-enrollment", formData);
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

export function getTranscriptionOptions(): Promise<TranscriptionOptions> {
  return apiFetch<TranscriptionOptions>("/api/settings/transcription-options");
}

export function createDictationBenchmarkBattle(input: {
  audio: Blob;
  filename?: string;
  language?: string;
}): Promise<DictationBenchmarkBattleResponse> {
  const formData = new FormData();
  formData.append("audio", input.audio, input.filename ?? "dictation.webm");
  formData.append("language", input.language ?? "multi");
  return apiUpload<DictationBenchmarkBattleResponse>("/api/benchmarks/dictation/battle", formData);
}

export function submitDictationBenchmarkVote(input: {
  battle_id: string;
  selected_candidate_id: string;
  selected_provider: string;
  selected_model: string;
  language: string;
  candidate_count: number;
}): Promise<DictationBenchmarkVoteResponse> {
  return apiFetch<DictationBenchmarkVoteResponse>("/api/benchmarks/dictation/battle/vote", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateSettings(settings: Partial<UserSettings>): Promise<UserSettings> {
  return apiFetch<UserSettings>("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(settings),
  });
}

export function getTelegramLinkStatus(): Promise<TelegramLinkStatus> {
  return apiFetch<TelegramLinkStatus>("/api/telegram/link");
}

export function startTelegramLink(): Promise<TelegramPairing> {
  return apiFetch<TelegramPairing>("/api/telegram/link/start", { method: "POST" });
}

export function unlinkTelegram(): Promise<void> {
  return apiFetch<void>("/api/telegram/link", { method: "DELETE" });
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

export async function exportSharedRecording(
  token: string,
  format: Extract<ExportFormat, "markdown">,
): Promise<Blob> {
  const response = await apiFetchResponse(
    `/api/recordings/shared/${token}/export?format=${format}`,
  );
  return response.blob();
}

export function createRecordingShareLink(recordingId: string): Promise<RecordingShareLink> {
  return apiFetch<RecordingShareLink>(`/api/recordings/${recordingId}/share`, {
    method: "POST",
  });
}

export function getSharedRecording(token: string): Promise<SharedRecording> {
  return apiFetch<SharedRecording>(`/api/recordings/shared/${token}`);
}

export function listMcpConnections(): Promise<McpConnection[]> {
  return apiFetch<McpConnection[]>("/api/mcp/oauth/connections");
}

export function revokeMcpConnection(clientId: string): Promise<void> {
  return apiFetch<void>(
    `/api/mcp/oauth/connections/${encodeURIComponent(clientId)}/revoke`,
    { method: "POST" },
  );
}

export function listApiKeys(): Promise<ApiKey[]> {
  return apiFetch<ApiKey[]>("/api/api-keys");
}

export function createApiKey(name: string, expiresAt?: string | null): Promise<ApiKeyCreated> {
  return apiFetch<ApiKeyCreated>("/api/api-keys", {
    method: "POST",
    body: JSON.stringify({ name, expires_at: expiresAt ?? null }),
  });
}

export function revokeApiKey(id: string): Promise<void> {
  return apiFetch<void>(`/api/api-keys/${encodeURIComponent(id)}/revoke`, { method: "POST" });
}
