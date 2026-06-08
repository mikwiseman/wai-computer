import {
  ApiError,
  apiFetch,
  apiFetchResponse,
  apiUpload,
  syncLocalhostAuthCookie,
  syncLocalhostRefreshCookie,
} from "./http";
import type {
  AnalyticsResponse,
  Agent,
  AgentActionListResponse,
  AgentCapabilitiesResponse,
  AgentCreateRequest,
  AgentListResponse,
  AgentRun,
  AgentRunListResponse,
  AgentStepListResponse,
  AgentUpdateRequest,
  ApiKey,
  ApiKeyCreated,
  BrainContextResponse,
  BrainExportResponse,
  BrainGraph,
  BrainMap,
  BrainMapProjection,
  BrainMapRevision,
  BrainMapsResponse,
  BrainPage,
  BrainPagesResponse,
  BrainReviewPack,
  BrainReviewPacksResponse,
  BrainSpace,
  BrainSpaceMember,
  BrainSpaceHome,
  BrainSpacesResponse,
  BrainSourceScope,
  BrainSyncResult,
  ComparisonListEntry,
  EntityPage,
  Entity,
  EntityType,
  BrainAnswer,
  ComparisonSet,
  Item,
  ItemListResponse,
  McpIngestionConnection,
  SourceCatalog,
  UnifiedSearchResponse,
  BulkAction,
  BulkOperationResponse,
  DictationBenchmarkBattleResponse,
  DictationBenchmarkVoteResponse,
  DictationDictionaryWord,
  DictationEntry,
  DataOwnershipMap,
  ExportFormat,
  ExportLocale,
  Folder,
  InboxResponse,
  InboxSourceKind,
  InboxStatusFilter,
  KeywordsResponse,
  McpConnection,
  MemoryProposal,
  MemoryProposalList,
  MessageResponse,
  Person,
  PersonalizationImportJob,
  PersonalizationTerm,
  PersonalizationTermStatus,
  StarRecordingResponse,
  VoiceEnrollmentResponse,
  Recording,
  RecordingDetail,
  RecordingType,
  RelatedRecordingsResponse,
  RealtimeSessionResponse,
  RecordingShareLink,
  Reminder,
  ReminderCreateRequest,
  ReminderListResponse,
  ReminderStatus,
  RematchSpeakersResponse,
  ResolveAgentActionResponse,
  SearchResponse,
  SelfHostMigrationPreflight,
  SelfHostMigrationContract,
  SelfHostProvisionRequest,
  SelfHostProvisionResponse,
  StartAgentRunRequest,
  TranscriptSegmentInput,
  SpeakerStatsResponse,
  SharedRecording,
  Summary,
  SummaryAudio,
  SummaryGeneration,
  SystemInfo,
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

export const LEGAL_TERMS_VERSION = "2026-05-22";
export const LEGAL_PRIVACY_VERSION = "2026-05-22";

interface LegalAcceptanceOptions {
  acceptedLegalTerms?: boolean;
}

export function register(
  email: string,
  password: string,
  options: AuthLocaleOptions & LegalAcceptanceOptions = {},
): Promise<TokenResponse> {
  return withLocalhostAuth(
    apiFetch<TokenResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        ...(options.locale ? { locale: options.locale } : {}),
        ...(options.region ? { region: options.region } : {}),
        accepted_legal_terms: options.acceptedLegalTerms === true,
        legal_terms_version: LEGAL_TERMS_VERSION,
        legal_privacy_version: LEGAL_PRIVACY_VERSION,
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
  options: AuthLocaleOptions & LegalAcceptanceOptions = {},
): Promise<MessageResponse> {
  return apiFetch<MessageResponse>("/api/auth/magic-link", {
    method: "POST",
    body: JSON.stringify({
      email,
      ...(options.locale ? { locale: options.locale } : {}),
      ...(options.region ? { region: options.region } : {}),
      ...(options.acceptedLegalTerms !== undefined
        ? {
            accepted_legal_terms: options.acceptedLegalTerms,
            legal_terms_version: LEGAL_TERMS_VERSION,
            legal_privacy_version: LEGAL_PRIVACY_VERSION,
          }
        : {}),
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

export function getSystemInfo(): Promise<SystemInfo> {
  return apiFetch<SystemInfo>("/api/system/info");
}

export function getDataOwnershipMap(): Promise<DataOwnershipMap> {
  return apiFetch<DataOwnershipMap>("/api/system/data-map");
}

export function getSelfHostMigrationPreflight(): Promise<SelfHostMigrationPreflight> {
  return apiFetch<SelfHostMigrationPreflight>("/api/self-host/migration/preflight");
}

export function getSelfHostMigrationContract(): Promise<SelfHostMigrationContract> {
  return apiFetch<SelfHostMigrationContract>("/api/self-host/migration/contract");
}

export function startSelfHostProvision(
  input: SelfHostProvisionRequest,
): Promise<SelfHostProvisionResponse> {
  return apiFetch<SelfHostProvisionResponse>("/api/self-host/provision", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function deleteAccount(): Promise<MessageResponse> {
  return apiFetch<MessageResponse>("/api/auth/me", { method: "DELETE" });
}

export function getAgentCapabilities(): Promise<AgentCapabilitiesResponse> {
  return apiFetch<AgentCapabilitiesResponse>("/api/agents/capabilities");
}

export function listAgents(params?: { limit?: number }): Promise<AgentListResponse> {
  return apiFetch<AgentListResponse>(`/api/agents${asQuery({ limit: params?.limit })}`);
}

export function createAgent(input: AgentCreateRequest): Promise<Agent> {
  return apiFetch<Agent>("/api/agents", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateAgent(agentId: string, input: AgentUpdateRequest): Promise<Agent> {
  return apiFetch<Agent>(`/api/agents/${agentId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteAgent(agentId: string): Promise<void> {
  await apiFetchResponse(`/api/agents/${agentId}`, { method: "DELETE" });
}

export function startAgentRun(
  agentId: string,
  input: StartAgentRunRequest = {},
): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/api/agents/${agentId}/runs`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listAgentRuns(
  agentId: string,
  params?: { status?: string; limit?: number },
): Promise<AgentRunListResponse> {
  return apiFetch<AgentRunListResponse>(
    `/api/agents/${agentId}/runs${asQuery({ status: params?.status, limit: params?.limit })}`,
  );
}

export function listAllAgentRuns(params?: {
  status?: string;
  limit?: number;
}): Promise<AgentRunListResponse> {
  return apiFetch<AgentRunListResponse>(
    `/api/agents/runs${asQuery({ status: params?.status, limit: params?.limit })}`,
  );
}

export function getAgentRun(agentId: string, runId: string): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/api/agents/${agentId}/runs/${runId}`);
}

export function listAgentRunSteps(
  agentId: string,
  runId: string,
): Promise<AgentStepListResponse> {
  return apiFetch<AgentStepListResponse>(`/api/agents/${agentId}/runs/${runId}/steps`);
}

export function cancelAgentRun(
  agentId: string,
  runId: string,
  reason?: string | null,
): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/api/agents/${agentId}/runs/${runId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

export function listAgentActions(params?: {
  status?: string;
  limit?: number;
}): Promise<AgentActionListResponse> {
  return apiFetch<AgentActionListResponse>(
    `/api/agents/actions${asQuery({ status: params?.status, limit: params?.limit })}`,
  );
}

export function listAgentRunActions(
  agentId: string,
  runId: string,
): Promise<AgentActionListResponse> {
  return apiFetch<AgentActionListResponse>(`/api/agents/${agentId}/runs/${runId}/actions`);
}

export function resolveAgentAction(
  agentId: string,
  runId: string,
  actionId: string,
  input: { decision: "once" | "always" | "reject"; edited_args?: Record<string, unknown> | null },
): Promise<ResolveAgentActionResponse> {
  return apiFetch<ResolveAgentActionResponse>(
    `/api/agents/${agentId}/runs/${runId}/actions/${actionId}/resolve`,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
}

export function listReminders(params?: {
  status?: ReminderStatus | "all";
  limit?: number;
}): Promise<ReminderListResponse> {
  return apiFetch<ReminderListResponse>(
    `/api/reminders${asQuery({ status: params?.status, limit: params?.limit })}`,
  );
}

export function createReminder(input: ReminderCreateRequest): Promise<Reminder> {
  return apiFetch<Reminder>("/api/reminders", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function cancelReminder(reminderId: string): Promise<Reminder> {
  return apiFetch<Reminder>(`/api/reminders/${reminderId}/cancel`, {
    method: "POST",
  });
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

export function listInbox(params?: {
  source_kind?: InboxSourceKind;
  status?: InboxStatusFilter;
  folder_id?: string | null;
  limit?: number;
  cursor?: string | null;
}): Promise<InboxResponse> {
  return apiFetch<InboxResponse>(
    `/api/inbox${asQuery({
      source_kind: params?.source_kind,
      status: params?.status,
      folder_id: params?.folder_id,
      limit: params?.limit,
      cursor: params?.cursor,
    })}`,
  );
}

export function createRecording(input: {
  title?: string | null;
  type?: RecordingType;
  language?: string;
  folder_id?: string | null;
}): Promise<Recording> {
  const body: {
    title: string | null;
    type: RecordingType;
    language: string;
    folder_id?: string | null;
  } = {
    title: input.title ?? null,
    type: input.type ?? "note",
    language: input.language ?? "multi",
  };
  if (input.folder_id !== undefined) {
    body.folder_id = input.folder_id;
  }
  return apiFetch<Recording>("/api/recordings", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getRecording(recordingId: string): Promise<RecordingDetail> {
  return apiFetch<RecordingDetail>(`/api/recordings/${recordingId}`);
}

export function updateRecording(
  recordingId: string,
  input: { title?: string | null; type?: RecordingType; folder_id?: string | null },
): Promise<Recording> {
  return apiFetch<Recording>(`/api/recordings/${recordingId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function assignRecordingToFolder(
  recordingId: string,
  folderId: string | null,
): Promise<Recording> {
  return apiFetch<Recording>(`/api/recordings/${recordingId}`, {
    method: "PATCH",
    body: JSON.stringify({ folder_id: folderId }),
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

export function rematchSpeakers(recordingId: string): Promise<RematchSpeakersResponse> {
  return apiFetch<RematchSpeakersResponse>(`/api/recordings/${recordingId}/rematch`, {
    method: "POST",
  });
}

export function createTranscriptionSession(input?: {
  language?: string;
  purpose?: "recording" | "dictation";
}): Promise<RealtimeSessionResponse> {
  return apiFetch<RealtimeSessionResponse>("/api/transcription/session", {
    method: "POST",
    body: JSON.stringify({
      language: input?.language ?? "multi",
      channels: 1,
      purpose: input?.purpose ?? "recording",
    }),
  });
}

export function saveTranscript(
  recordingId: string,
  segments: TranscriptSegmentInput[],
): Promise<RecordingDetail> {
  return apiFetch<RecordingDetail>(`/api/recordings/${recordingId}/transcript`, {
    method: "POST",
    body: JSON.stringify({ segments }),
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

export function getSummaryGeneration(recordingId: string): Promise<SummaryGeneration> {
  return apiFetch<SummaryGeneration>(`/api/recordings/${recordingId}/summary-generation`);
}

export function startSummaryGeneration(
  recordingId: string,
  input: { instructions?: string | null } = {},
): Promise<SummaryGeneration> {
  return apiFetch<SummaryGeneration>(`/api/recordings/${recordingId}/summary-generation`, {
    method: "POST",
    body: JSON.stringify({ instructions: input.instructions ?? null }),
  });
}

export function getRecordingSummaryAudio(recordingId: string): Promise<SummaryAudio> {
  return apiFetch<SummaryAudio>(`/api/recordings/${recordingId}/summary/audio`);
}

export function startRecordingSummaryAudio(recordingId: string): Promise<SummaryAudio> {
  return apiFetch<SummaryAudio>(`/api/recordings/${recordingId}/summary/audio`, {
    method: "POST",
  });
}

export async function downloadRecordingSummaryAudio(recordingId: string): Promise<Blob> {
  const response = await apiFetchResponse(
    `/api/recordings/${recordingId}/summary/audio/file`,
  );
  return response.blob();
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

// --- Second brain: universal search over recordings + items ---

export function unifiedSearch(params: {
  q: string;
  limit?: number;
}): Promise<UnifiedSearchResponse> {
  return apiFetch<UnifiedSearchResponse>(`/api/search/all${asQuery(params)}`);
}

// --- Second brain: items (add anything) ---

export function createItem(input: {
  source?: string;
  kind?: string;
  title?: string | null;
  body?: string | null;
  url?: string | null;
  folder_id?: string | null;
}): Promise<Item> {
  return apiFetch<Item>("/api/items", {
    method: "POST",
    body: JSON.stringify({ source: "paste", kind: "note", ...input }),
  });
}

/**
 * Result of "add any file": documents extract inline into an Item (201);
 * audio/video create a processing Recording immediately (202), then continue
 * through the background media import pipeline.
 */
export type UploadOutcome =
  | { kind: "item"; item: Item }
  | { kind: "recording"; status: string; recording_id: string };

export async function uploadItem(
  file: File,
  opts?: { folderId?: string; title?: string },
): Promise<UploadOutcome> {
  const formData = new FormData();
  formData.append("file", file);
  if (opts?.folderId) formData.append("folder_id", opts.folderId);
  if (opts?.title) formData.append("title", opts.title);
  const payload = await apiUpload<Item | { kind: "recording"; status: string; recording_id?: string }>(
    "/api/items/upload",
    formData,
  );
  if ("id" in payload) return { kind: "item", item: payload };
  if (!payload.recording_id) {
    throw new Error("Media upload response missing recording_id.");
  }
  return {
    kind: "recording",
    status: payload.status,
    recording_id: payload.recording_id,
  };
}

export function listItems(params?: {
  source?: string;
  kind?: string;
  folder_id?: string;
  limit?: number;
  offset?: number;
}): Promise<ItemListResponse> {
  return apiFetch<ItemListResponse>(`/api/items${asQuery(params ?? {})}`);
}

export function getItem(itemId: string): Promise<Item> {
  return apiFetch<Item>(`/api/items/${itemId}`);
}

export function getItemSummaryAudio(itemId: string): Promise<SummaryAudio> {
  return apiFetch<SummaryAudio>(`/api/items/${itemId}/summary/audio`);
}

export function startItemSummaryAudio(itemId: string): Promise<SummaryAudio> {
  return apiFetch<SummaryAudio>(`/api/items/${itemId}/summary/audio`, {
    method: "POST",
  });
}

export async function downloadItemSummaryAudio(itemId: string): Promise<Blob> {
  const response = await apiFetchResponse(`/api/items/${itemId}/summary/audio/file`);
  return response.blob();
}

export function deleteItem(itemId: string): Promise<void> {
  return apiFetch<void>(`/api/items/${itemId}`, { method: "DELETE" });
}

/** Recover a needs_input/failed item: paste the text we couldn't fetch (body),
 *  or omit it to retry the source URL. */
export function reprocessItem(itemId: string, input?: { body?: string }): Promise<Item> {
  return apiFetch<Item>(`/api/items/${itemId}/reprocess`, {
    method: "POST",
    body: JSON.stringify(input ?? {}),
  });
}

// --- Second brain: knowledge graph ---

export function getBrainGraph(params?: {
  focus?: string;
  include_sources?: boolean;
  limit?: number;
}): Promise<BrainGraph> {
  return apiFetch<BrainGraph>(`/api/brain/graph${asQuery(params ?? {})}`);
}

export function syncBrain(
  input: { limit?: number; includeChats?: boolean } = {},
): Promise<BrainSyncResult> {
  return apiFetch<BrainSyncResult>("/api/brain/sync", {
    method: "POST",
    body: JSON.stringify({
      limit: input.limit ?? 500,
      include_chats: input.includeChats ?? false,
    }),
  });
}

export function getBrainMirror(params?: { limit?: number }): Promise<BrainMapProjection> {
  return apiFetch<BrainMapProjection>(`/api/brain/mirror${asQuery(params ?? {})}`);
}

export function listBrainMaps(params?: {
  status?: string;
  limit?: number;
}): Promise<BrainMapsResponse> {
  return apiFetch<BrainMapsResponse>(`/api/brain/maps${asQuery(params ?? {})}`);
}

export function createBrainMap(input: {
  prompt: string;
  origin?: "brain" | "inbox" | "agent" | "wai";
  map_type?: string | null;
  title?: string | null;
  space_id?: string | null;
  source_scope?: Record<string, unknown> | null;
}): Promise<BrainMap> {
  return apiFetch<BrainMap>("/api/brain/maps", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getBrainMap(mapId: string): Promise<BrainMap> {
  return apiFetch<BrainMap>(`/api/brain/maps/${mapId}`);
}

export function updateBrainMap(
  mapId: string,
  input: {
    title?: string | null;
    status?: "draft" | "saved" | "archived" | string | null;
    layout?: Record<string, { x: number; y: number }> | null;
  },
): Promise<BrainMap> {
  return apiFetch<BrainMap>(`/api/brain/maps/${mapId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function refreshBrainMap(mapId: string): Promise<BrainMapRevision> {
  return apiFetch<BrainMapRevision>(`/api/brain/maps/${mapId}/refresh`, {
    method: "POST",
  });
}

export function listBrainMapRevisions(mapId: string): Promise<{ revisions: BrainMapRevision[] }> {
  return apiFetch<{ revisions: BrainMapRevision[] }>(`/api/brain/maps/${mapId}/revisions`);
}

export function listBrainSpaces(): Promise<BrainSpacesResponse> {
  return apiFetch<BrainSpacesResponse>("/api/brain/spaces");
}

export function createBrainSpace(input: {
  name: string;
  kind?: string;
  engine_profile?: string;
  visibility?: string;
  description?: string | null;
}): Promise<BrainSpace> {
  return apiFetch<BrainSpace>("/api/brain/spaces", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function addBrainSpaceMember(
  spaceId: string,
  input: { email: string; role: "viewer" | "editor" },
): Promise<BrainSpaceMember> {
  return apiFetch<BrainSpaceMember>(`/api/brain/spaces/${spaceId}/members`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getBrainSpaceHome(spaceId: string): Promise<BrainSpaceHome> {
  return apiFetch<BrainSpaceHome>(`/api/brain/spaces/${spaceId}/home`);
}

export function listBrainSpacePages(spaceId: string): Promise<BrainPagesResponse> {
  return apiFetch<BrainPagesResponse>(`/api/brain/spaces/${spaceId}/pages`);
}

export function createBrainSpacePage(
  spaceId: string,
  input: {
    title: string;
    kind?: string;
    markdown?: string | null;
    claims?: Array<{
      kind: string;
      text: string;
      confidence?: number;
      authority?: string;
      evidence?: unknown[] | null;
      source_refs?: unknown[] | null;
      salience?: number | null;
      metadata?: Record<string, unknown> | null;
    }>;
  },
): Promise<BrainPage> {
  return apiFetch<BrainPage>(`/api/brain/spaces/${spaceId}/pages`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listBrainReviewPacks(
  spaceId: string,
  params?: { status?: string },
): Promise<BrainReviewPacksResponse> {
  return apiFetch<BrainReviewPacksResponse>(
    `/api/brain/spaces/${spaceId}/review-packs${asQuery(params ?? {})}`,
  );
}

export function acceptBrainReviewPack(
  spaceId: string,
  packId: string,
): Promise<BrainReviewPack> {
  return apiFetch<BrainReviewPack>(
    `/api/brain/spaces/${spaceId}/review-packs/${packId}/accept`,
    { method: "POST" },
  );
}

export function rejectBrainReviewPack(
  spaceId: string,
  packId: string,
  reason?: string | null,
): Promise<BrainReviewPack> {
  return apiFetch<BrainReviewPack>(
    `/api/brain/spaces/${spaceId}/review-packs/${packId}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );
}

export function matchBrainSpaces(
  spaceId: string,
  otherSpaceId: string,
): Promise<BrainReviewPack> {
  return apiFetch<BrainReviewPack>(`/api/brain/spaces/${spaceId}/match`, {
    method: "POST",
    body: JSON.stringify({ other_space_id: otherSpaceId }),
  });
}

export function buildBrainContext(
  spaceId: string,
  input?: { task?: string | null; limit?: number },
): Promise<BrainContextResponse> {
  return apiFetch<BrainContextResponse>(`/api/brain/spaces/${spaceId}/context`, {
    method: "POST",
    body: JSON.stringify(input ?? {}),
  });
}

export function exportBrainSpace(
  spaceId: string,
  profile = "obsidian",
): Promise<BrainExportResponse> {
  return apiFetch<BrainExportResponse>(
    `/api/brain/spaces/${spaceId}/export${asQuery({ profile })}`,
  );
}

export function getEntityPage(entityId: string): Promise<EntityPage> {
  return apiFetch<EntityPage>(`/api/entities/${entityId}/page`);
}

// --- Second brain: Pages (entities) + Ask your Brain ---

export function listEntities(params?: {
  type?: EntityType;
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<Entity[]> {
  return apiFetch<Entity[]>(`/api/entities${asQuery(params ?? {})}`);
}

export function askBrain(question: string, sourceScope?: BrainSourceScope): Promise<BrainAnswer> {
  return apiFetch<BrainAnswer>("/api/brain/ask", {
    method: "POST",
    body: JSON.stringify({
      question,
      ...(sourceScope ? { source_scope: sourceScope } : {}),
    }),
  });
}

export function listMemoryProposals(params?: {
  status?: string;
  limit?: number;
}): Promise<MemoryProposalList> {
  return apiFetch<MemoryProposalList>(
    `/api/memory/proposals${asQuery({ status: "pending", limit: 50, ...(params ?? {}) })}`,
  );
}

export function acceptMemoryProposal(id: string): Promise<MemoryProposal> {
  return apiFetch<MemoryProposal>(`/api/memory/proposals/${id}/accept`, {
    method: "POST",
  });
}

export function rejectMemoryProposal(
  id: string,
  reason?: string | null,
): Promise<MemoryProposal> {
  return apiFetch<MemoryProposal>(`/api/memory/proposals/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

// --- Second brain: comparison sets ---

export function createComparison(input: {
  item_ids: string[];
  title?: string | null;
  intent?: string | null;
}): Promise<ComparisonSet> {
  return apiFetch<ComparisonSet>("/api/comparisons", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listComparisons(params?: {
  limit?: number;
  offset?: number;
}): Promise<ComparisonListEntry[]> {
  return apiFetch<ComparisonListEntry[]>(`/api/comparisons${asQuery(params ?? {})}`);
}

export function getComparison(comparisonId: string): Promise<ComparisonSet> {
  return apiFetch<ComparisonSet>(`/api/comparisons/${comparisonId}`);
}

export function deleteComparison(comparisonId: string): Promise<void> {
  return apiFetch<void>(`/api/comparisons/${comparisonId}`, { method: "DELETE" });
}

// --- Second brain: connect any MCP (ingestion sources) ---

export function listMcpIngestionConnections(): Promise<McpIngestionConnection[]> {
  return apiFetch<McpIngestionConnection[]>("/api/mcp-connections");
}

export function getSourceCatalog(): Promise<SourceCatalog> {
  return apiFetch<SourceCatalog>("/api/source-catalog");
}

export function createMcpIngestionConnection(input: {
  catalog_id?: string;
  server_label?: string;
  server_url?: string;
  transport?: string;
  auth_type?: string;
  auth_token?: string | null;
  sync_interval_minutes?: number;
  privacy_level?: string;
  backfill_depth?: string;
}): Promise<McpIngestionConnection> {
  return apiFetch<McpIngestionConnection>("/api/mcp-connections", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateMcpIngestionConnection(
  connectionId: string,
  input: { enabled?: boolean; sync_interval_minutes?: number; server_label?: string },
): Promise<McpIngestionConnection> {
  return apiFetch<McpIngestionConnection>(`/api/mcp-connections/${connectionId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function syncMcpIngestionConnection(connectionId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/api/mcp-connections/${connectionId}/sync`, {
    method: "POST",
  });
}

export function deleteMcpIngestionConnection(connectionId: string): Promise<void> {
  return apiFetch<void>(`/api/mcp-connections/${connectionId}`, { method: "DELETE" });
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

export interface AppearancePreferences {
  theme: string;
  accent: string;
}

export function getPreferences(): Promise<AppearancePreferences> {
  return apiFetch<AppearancePreferences>("/api/settings/preferences");
}

export function updatePreferences(
  patch: { theme?: string; accent?: string },
): Promise<AppearancePreferences> {
  return apiFetch<AppearancePreferences>("/api/settings/preferences", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export interface UserIdentity {
  first_name: string | null;
  last_name: string | null;
  has_voiceprint: boolean;
}

export interface UpdateIdentityRequest {
  first_name?: string | null;
  last_name?: string | null;
}

export interface VoiceSharingState {
  enabled: boolean;
  can_enable: boolean;
  has_first_name: boolean;
  has_last_name: boolean;
  has_voiceprint: boolean;
  shared_name: string | null;
}

export function getIdentity(): Promise<UserIdentity> {
  return apiFetch<UserIdentity>("/api/settings/identity");
}

export function updateIdentity(patch: UpdateIdentityRequest): Promise<UserIdentity> {
  return apiFetch<UserIdentity>("/api/settings/identity", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function getVoiceSharing(): Promise<VoiceSharingState> {
  return apiFetch<VoiceSharingState>("/api/settings/voice-sharing");
}

export function enableVoiceSharing(): Promise<VoiceSharingState> {
  return apiFetch<VoiceSharingState>("/api/settings/voice-sharing", {
    method: "POST",
  });
}

export function disableVoiceSharing(): Promise<VoiceSharingState> {
  return apiFetch<VoiceSharingState>("/api/settings/voice-sharing", {
    method: "DELETE",
  });
}

export function getTelegramLinkStatus(): Promise<TelegramLinkStatus> {
  return apiFetch<TelegramLinkStatus>("/api/telegram/link");
}

export function startTelegramLink(): Promise<TelegramPairing> {
  return apiFetch<TelegramPairing>("/api/telegram/link/start", { method: "POST" });
}

export function claimTelegramLinkCode(code: string): Promise<TelegramLinkStatus> {
  return apiFetch<TelegramLinkStatus>("/api/telegram/link/claim", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
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

export async function exportRecording(
  recordingId: string,
  format: ExportFormat,
  options: { locale?: ExportLocale } = {},
): Promise<Blob> {
  const response = await apiFetchResponse(
    `/api/recordings/${recordingId}/export${asQuery({ format, locale: options.locale })}`,
  );
  return response.blob();
}

export async function exportSharedRecording(
  token: string,
  format: Extract<ExportFormat, "markdown">,
  options: { locale?: ExportLocale } = {},
): Promise<Blob> {
  const response = await apiFetchResponse(
    `/api/recordings/shared/${token}/export${asQuery({ format, locale: options.locale })}`,
  );
  return response.blob();
}

export function listPersonalizationTerms(params?: {
  status?: PersonalizationTermStatus | "all";
}): Promise<PersonalizationTerm[]> {
  return apiFetch<PersonalizationTerm[]>(`/api/personalization/terms${asQuery(params || {})}`);
}

export function createPersonalizationTerm(input: {
  term: string;
  replacement?: string | null;
  notes?: string | null;
}): Promise<PersonalizationTerm> {
  return apiFetch<PersonalizationTerm>("/api/personalization/terms", {
    method: "POST",
    body: JSON.stringify({
      term: input.term,
      replacement: input.replacement ?? null,
      notes: input.notes ?? null,
    }),
  });
}

export function updatePersonalizationTerm(
  termId: string,
  input: {
    status?: PersonalizationTermStatus;
    replacement?: string | null;
    notes?: string | null;
  },
): Promise<PersonalizationTerm> {
  return apiFetch<PersonalizationTerm>(`/api/personalization/terms/${termId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deletePersonalizationTerm(termId: string): Promise<void> {
  return apiFetch<void>(`/api/personalization/terms/${termId}`, { method: "DELETE" });
}

export function importPersonalizationText(text: string): Promise<PersonalizationImportJob> {
  const formData = new FormData();
  formData.append("source_type", "text");
  formData.append("text", text);
  return apiUpload<PersonalizationImportJob>("/api/personalization/imports", formData);
}

export function importPersonalizationFile(file: File): Promise<PersonalizationImportJob> {
  const formData = new FormData();
  formData.append("source_type", "file");
  formData.append("file", file);
  return apiUpload<PersonalizationImportJob>("/api/personalization/imports", formData);
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

export function createApiKey(
  name: string,
  options: { expiresAt?: string | null; allowMemoryWrite?: boolean } = {},
): Promise<ApiKeyCreated> {
  return apiFetch<ApiKeyCreated>("/api/api-keys", {
    method: "POST",
    body: JSON.stringify({
      name,
      expires_at: options.expiresAt ?? null,
      allow_memory_write: options.allowMemoryWrite ?? false,
    }),
  });
}

export function revokeApiKey(id: string): Promise<void> {
  return apiFetch<void>(`/api/api-keys/${encodeURIComponent(id)}/revoke`, { method: "POST" });
}

export function listFolders(): Promise<Folder[]> {
  return apiFetch<Folder[]>("/api/folders");
}

export function createFolder(name: string): Promise<Folder> {
  return apiFetch<Folder>("/api/folders", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function renameFolder(id: string, name: string): Promise<Folder> {
  return apiFetch<Folder>(`/api/folders/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export function deleteFolder(id: string): Promise<void> {
  return apiFetch<void>(`/api/folders/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function listDictationEntries(): Promise<DictationEntry[]> {
  return apiFetch<DictationEntry[]>("/api/dictation/entries");
}

export function cleanupDictation(text: string, vocabulary?: string[]): Promise<{ text: string }> {
  return apiFetch<{ text: string }>("/api/dictation/cleanup", {
    method: "POST",
    body: JSON.stringify({
      text,
      vocabulary: vocabulary && vocabulary.length > 0 ? vocabulary : null,
    }),
  });
}

export function createDictationEntry(input: {
  client_entry_id: string;
  raw_text: string;
  cleaned_text?: string | null;
  duration_seconds: number;
  word_count: number;
  occurred_at: string;
}): Promise<DictationEntry> {
  return apiFetch<DictationEntry>("/api/dictation/entries", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function deleteDictationEntry(clientEntryId: string): Promise<void> {
  return apiFetch<void>(`/api/dictation/entries/${encodeURIComponent(clientEntryId)}`, {
    method: "DELETE",
  });
}

export function listDictionaryWords(): Promise<DictationDictionaryWord[]> {
  return apiFetch<DictationDictionaryWord[]>("/api/dictation/dictionary");
}

export function createDictionaryWord(input: {
  word: string;
  replacement?: string | null;
}): Promise<DictationDictionaryWord> {
  return apiFetch<DictationDictionaryWord>("/api/dictation/dictionary", {
    method: "POST",
    body: JSON.stringify({
      client_word_id: cryptoRandomUUID(),
      word: input.word,
      replacement: input.replacement ?? null,
      occurred_at: new Date().toISOString(),
    }),
  });
}

export function deleteDictionaryWord(id: string): Promise<void> {
  return apiFetch<void>(`/api/dictation/dictionary/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

// Minimal UUID v4 generator usable both in the browser and in the jsdom test env.
// Backend treats `client_word_id` as the idempotency key; any RFC4122 UUID works.
function cryptoRandomUUID(): string {
  const g = globalThis as { crypto?: { randomUUID?: () => string } };
  if (g.crypto && typeof g.crypto.randomUUID === "function") {
    return g.crypto.randomUUID();
  }
  // RFC4122-ish fallback — only used in environments without `crypto.randomUUID`.
  const hex = (n: number) => Math.floor(Math.random() * 16 ** n).toString(16).padStart(n, "0");
  return `${hex(8)}-${hex(4)}-4${hex(3)}-${(8 + Math.floor(Math.random() * 4)).toString(16)}${hex(3)}-${hex(12)}`;
}
