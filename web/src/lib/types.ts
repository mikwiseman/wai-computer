export type RecordingType = "meeting" | "note" | "reflection";
export type ActionStatus = "pending" | "in_progress" | "completed" | "cancelled";
export type ActionPriority = "high" | "medium" | "low";
export type ExportFormat = "markdown" | "txt" | "srt";
export type ExportLocale = "en" | "ru";
export type RealtimeVoiceMode = "conversation" | "recording";
export type DeploymentMode = "wai_cloud" | "self_host" | "provisioning";

export type SummaryStyle = "brief" | "medium" | "detailed";
export type DictationCleanupLevel = "none" | "light" | "medium" | "high";

export interface UserSettings {
  default_language: string;
  summary_language: string;
  summary_style: SummaryStyle;
  summary_instructions: string | null;
  dictation_live_stt_provider: string;
  dictation_live_stt_model: string;
  recording_live_stt_provider: string;
  recording_live_stt_model: string;
  file_stt_provider: string;
  file_stt_model: string;
  dictation_post_filter_enabled: boolean;
  dictation_cleanup_level: DictationCleanupLevel;
  dictation_post_filter_provider: string;
  dictation_post_filter_model: string;
}

export interface SystemInfo {
  app_name: string;
  deployment_mode: DeploymentMode;
  public_base_url: string;
  cloud_base_url: string;
  mcp_url: string;
  git_sha: string | null;
  git_dirty: boolean;
  audio_retention_policy: "delete_after_processing";
  self_hosting_available: boolean;
  billing_mode: "cloud" | "self_host";
}

export type OwnershipClassification =
  | "owned_exportable"
  | "self_host_local"
  | "hosted_control_plane"
  | "reconnect_required"
  | "excluded_with_reason";

export interface OwnershipEntry {
  name: string;
  table?: string;
  classification: OwnershipClassification;
  reason: string;
  contains_user_content: boolean;
  requires_reconnect: boolean;
  path_hint?: string | null;
}

export interface DataOwnershipMap {
  audio_retention_policy: "delete_after_processing";
  tables: OwnershipEntry[];
  artifacts: OwnershipEntry[];
}

export interface SelfHostProvisionRequest {
  hostname?: string | null;
  vps_ip: string;
  ssh_username: string;
  auth_method: "ssh_key" | "password";
  ssh_public_key?: string | null;
  ssh_password?: string | null;
}

export interface SelfHostProvisionStep {
  id: string;
  label: string;
  status: "pending" | "manual_review_required" | "blocked";
}

export interface SelfHostProvisionResponse {
  job_id: string;
  status: "manual_review_required";
  hostname: string | null;
  vps_ip: string;
  steps: SelfHostProvisionStep[];
  message: string;
}

export interface SelfHostMigrationPreflight {
  status: "manual_review_required";
  owned_exportable: string[];
  reconnect_required: string[];
  server_local: string[];
  excluded: string[];
  data_map: DataOwnershipMap;
}

export interface SelfHostMigrationContractGroup {
  tables: Array<Record<string, unknown>>;
  artifacts: Array<Record<string, unknown>>;
}

export interface SelfHostMigrationContract {
  schema_version: string;
  archive_format: string;
  requires_same_alembic_head: boolean;
  preserve_user_ids: boolean;
  collision_policy: "reject";
  secret_policy: string;
  owned_exportable: SelfHostMigrationContractGroup;
  reconnect_required: SelfHostMigrationContractGroup;
  server_local: SelfHostMigrationContractGroup;
  excluded: SelfHostMigrationContractGroup;
}

export type AgentTriggerType = "manual" | "cron" | "event" | "signal" | "chat";
export type AgentRunTriggerKind = AgentTriggerType | "telegram" | "agent";
export type AgentRunStatus =
  | "pending"
  | "planning"
  | "running"
  | "awaiting_approval"
  | "done"
  | "failed"
  | "expired"
  | "skipped"
  | "cancelled";

export interface Agent {
  id: string;
  name: string;
  kind: string;
  trigger_type: AgentTriggerType;
  config: Record<string, unknown>;
  autonomy: "propose" | string;
  enabled: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentListResponse {
  agents: Agent[];
}

export interface AgentCreateRequest {
  name: string;
  kind?: string;
  trigger_type?: AgentTriggerType;
  config?: Record<string, unknown>;
  autonomy?: "propose";
  enabled?: boolean;
  next_run_at?: string | null;
}

export interface AgentUpdateRequest {
  name?: string;
  kind?: string;
  trigger_type?: AgentTriggerType;
  config?: Record<string, unknown>;
  autonomy?: "propose";
  enabled?: boolean;
  next_run_at?: string | null;
}

export interface AgentRun {
  id: string;
  agent_id: string;
  parent_run_id: string | null;
  parent_step_idx: number | null;
  trigger_key: string;
  trigger_kind: AgentRunTriggerKind;
  trigger_payload: Record<string, unknown> | null;
  status: AgentRunStatus;
  plan: Record<string, unknown> | null;
  done_spec: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  content_hash: string | null;
  error: string | null;
  next_step_idx: number;
  heartbeat_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  cancel_requested_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentRunListResponse {
  runs: AgentRun[];
}

export interface AgentStep {
  id: string;
  run_id: string;
  idx: number;
  kind: string;
  payload: Record<string, unknown>;
  idempotency_key: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentStepListResponse {
  steps: AgentStep[];
}

export interface AgentAction {
  id: string;
  agent_id: string | null;
  run_id: string | null;
  step_idx: number | null;
  kind: string;
  tool: string;
  status: string;
  preview: string;
  recipient: string | null;
  expires_at: string;
  resolved_at: string | null;
  receipt: Record<string, unknown> | null;
}

export interface AgentActionListResponse {
  actions: AgentAction[];
}

export interface AgentCapability {
  id: string;
  label: string;
  category: string;
  description: string;
  availability: "available" | "approval_required" | "self_host_only" | "planned";
  runtime_tool: string | null;
  surfaces: string[];
  requires_approval: boolean;
  cloud_supported: boolean;
  self_host_supported: boolean;
  local_gateway_required: boolean;
  risk_level: string;
  permission_scopes: string[];
  safety_notes: string;
}

export interface AgentToolContract {
  name: string;
  capability_id: string;
  kind: "runtime" | "action";
  description: string;
  side_effect: string;
  requires_approval: boolean;
  args_schema: Record<string, unknown>;
  result_schema: Record<string, unknown>;
  permission_scopes: string[];
}

export interface AgentRuntimeMode {
  id: string;
  label: string;
  description: string;
  available: boolean;
}

export interface AgentCapabilitiesResponse {
  schema_version: string;
  deployment_mode: DeploymentMode;
  max_steps: number;
  runtime_modes: AgentRuntimeMode[];
  capabilities: AgentCapability[];
  tool_contracts: AgentToolContract[];
}

export interface StartAgentRunRequest {
  trigger_kind?: AgentRunTriggerKind;
  trigger_payload?: Record<string, unknown>;
  content_hash?: string | null;
  idempotency_key?: string | null;
  run_inline?: boolean;
}

export interface ResolveAgentActionResponse {
  action_id: string;
  status: string;
  run_status: AgentRunStatus;
  recipient?: string | null;
}

export type ReminderStatus = "pending" | "sent" | "failed" | "cancelled";
export type ReminderSource = "api" | "web" | "mac" | "telegram";

export interface Reminder {
  id: string;
  text: string;
  due_at: string;
  status: ReminderStatus;
  source: ReminderSource | string;
  source_ref: string | null;
  sent_at: string | null;
  failed_at: string | null;
  error: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ReminderListResponse {
  reminders: Reminder[];
}

export interface ReminderCreateRequest {
  text: string;
  due_at: string;
  source?: "api" | "web" | "mac";
  metadata?: Record<string, unknown>;
}

export interface TelegramLinkStatus {
  linked: boolean;
  bot_username: string;
  telegram_user_id: number | null;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  linked_at: string | null;
}

export interface TelegramPairing {
  bot_username: string;
  deep_link: string;
  web_link: string;
  expires_at: string;
}

export interface TranscriptionModelOption {
  provider: string;
  model: string;
  label: string;
  description: string;
}

export interface TranscriptionOptions {
  dictation_live_stt: TranscriptionModelOption[];
  recording_live_stt: TranscriptionModelOption[];
  file_stt: TranscriptionModelOption[];
  dictation_post_filter: TranscriptionModelOption[];
}

export interface DictationBenchmarkCandidate {
  id: string;
  provider: string;
  model: string;
  label: string;
  status: "standby" | "listening" | "running" | "ok" | "error";
  transcript: string | null;
  latency_ms: number | null;
  word_count: number | null;
  error: string | null;
}

export interface DictationBenchmarkBattleResponse {
  battle_id: string;
  language: string;
  candidates: DictationBenchmarkCandidate[];
}

export interface DictationBenchmarkVoteResponse {
  vote_id: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  token_type: string;
}

export interface MessageResponse {
  message: string;
}

export interface User {
  id: string;
  email: string;
  created_at: string;
  has_password: boolean;
  // True once the account has enrolled a voice — server-side source of truth for
  // "already onboarded" so a returning user skips voice onboarding on any device.
  has_enrolled_voice?: boolean;
  theme?: "system" | "light" | "dark";
  accent?: "teal" | "amber" | "blue" | "green" | "violet" | "rose" | "graphite";
}

export interface Recording {
  id: string;
  title: string | null;
  type: RecordingType;
  audio_url: string | null;
  status: string;
  failure_code: string | null;
  failure_message: string | null;
  uploaded_at: string | null;
  duration_seconds: number | null;
  language: string | null;
  folder_id: string | null;
  deleted_at: string | null;
  starred_at: string | null;
  created_at: string;
  updated_at?: string;
}

export interface Segment {
  id: string;
  speaker: string | null;
  raw_label: string | null;
  person_id: string | null;
  display_name: string | null;
  auto_assigned: boolean;
  match_confidence: number | null;
  content: string;
  start_ms: number | null;
  end_ms: number | null;
  confidence: number | null;
}

export interface Person {
  id: string;
  display_name: string;
  color: string | null;
  aliases: string[] | null;
  voiceprint_count: number;
  created_at: string;
  updated_at: string;
}

export interface VoiceEnrollmentResponse {
  person: Person;
  voiceprint_id: string;
  duration_s: number;
}

export interface Summary {
  summary: string | null;
  key_points: string[] | null;
  decisions: Array<Record<string, unknown>> | null;
  topics: string[] | null;
  people_mentioned: string[] | null;
  sentiment: string | null;
}

export interface SummaryGeneration {
  job_id: string | null;
  recording_id: string;
  status: "not_started" | "queued" | "running" | "succeeded" | "failed";
  stage: string;
  progress_percent: number;
  message: string;
  requested_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface SummaryAudio {
  artifact_id: string | null;
  source_kind: "recording" | "item";
  source_id: string;
  status: "not_started" | "queued" | "running" | "succeeded" | "failed";
  stage: string;
  progress_percent: number;
  message: string;
  provider: string | null;
  model: string | null;
  voice_id: string | null;
  language: string | null;
  content_type: string | null;
  byte_size: number | null;
  duration_seconds: number | null;
  audio_url: string | null;
  requested_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  error_code: string | null;
  error_message: string | null;
}

export type PersonalizationTermStatus = "active" | "candidate" | "rejected";

export interface PersonalizationTerm {
  id: string;
  user_id: string;
  import_job_id: string | null;
  term: string;
  normalized_term: string;
  replacement: string | null;
  notes: string | null;
  source: "manual" | "import";
  status: PersonalizationTermStatus;
  frequency: number;
  created_at: string;
  updated_at: string;
}

export interface PersonalizationImportJob {
  id: string;
  user_id: string;
  source_type: string;
  source_name: string | null;
  status: "queued" | "running" | "succeeded" | "failed";
  candidate_count: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ActionItem {
  id: string;
  recording_id: string;
  task: string;
  owner: string | null;
  due_date: string | null;
  priority: ActionPriority | null;
  status: ActionStatus;
  source: string;
  created_at: string;
}

export type HighlightCategory =
  | "decision"
  | "insight"
  | "question"
  | "concern"
  | "topic_shift"
  | "quote";
export type HighlightImportance = "high" | "medium" | "low";

export interface Highlight {
  id: string;
  recording_id: string;
  category: HighlightCategory;
  title: string;
  description: string | null;
  speaker: string | null;
  start_ms: number | null;
  end_ms: number | null;
  importance: HighlightImportance;
}

export interface RecordingDetail extends Recording {
  segments: Segment[];
  summary: Summary | null;
  summary_generation?: SummaryGeneration | null;
  summary_audio: SummaryAudio;
  action_items: ActionItem[];
  highlights: Highlight[];
}

export type InboxSourceKind = "recording" | "item" | "chat";
export type InboxStatus = "ready" | "processing" | "needs_input" | "failed" | "archived";
export type InboxStatusFilter = "ready" | "processing" | "needs_attention";

export interface InboxDetailRef {
  kind: InboxSourceKind;
  id: string;
}

export interface InboxError {
  code: string;
  message: string;
}

export interface InboxRow {
  id: string;
  source_kind: InboxSourceKind;
  source_id: string;
  detail: InboxDetailRef;
  title: string | null;
  source_label: string;
  sublabel: string | null;
  activity_at: string;
  created_at: string;
  updated_at: string | null;
  occurred_at: string | null;
  status: InboxStatus;
  source_status: string | null;
  error: InboxError | null;
  folder_id: string | null;
  duration_seconds: number | null;
  language: string | null;
  has_summary: boolean | null;
  is_starred: boolean;
  is_pinned: boolean;
  is_archived: boolean;
  is_trashed: boolean;
}

export interface InboxResponse {
  rows: InboxRow[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface RematchSpeakersResponse {
  recording_id: string;
  updated_clusters: number;
  matched_clusters: number;
}

export interface RealtimeSessionResponse {
  provider: string;
  token: string;
  expires_in_seconds: number;
  sample_rate: number;
  audio_format: string;
  language: string;
  channels: number;
  model: string;
  keep_alive_interval_seconds: number | null;
  commit_strategy: string | null;
  no_verbatim: boolean;
  websocket_url: string | null;
  auth_scheme: string;
}

export interface TranscriptSegmentInput {
  text: string;
  speaker?: string | null;
  start_ms: number;
  end_ms: number;
  confidence?: number | null;
}

export interface RecordingShareLink {
  recording_id: string;
  token: string;
  url: string;
  created_at: string;
}

export type CompanionMessageRole = "user" | "assistant" | "tool";

export interface CompanionScope {
  recording_ids?: string[];
  brain_space_id?: string;
  // "Ask Wai about X" scopes the chat to one entity's compiled page.
  entity_id?: string;
  folder_ids?: string[];
  types?: string[];
  speakers?: string[];
  date_from?: string;
  date_to?: string;
}

export interface CompanionConversation {
  id: string;
  title: string | null;
  scope: CompanionScope | null;
  pinned_at: string | null;
  last_message_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompanionCitation {
  id: string;
  segment_id: string | null;
  recording_id: string | null;
  span_start: number;
  span_end: number;
  citation_index: number;
}

export interface CompanionMessage {
  id: string;
  role: CompanionMessageRole;
  status?: "streaming" | "complete" | "failed" | string;
  content: unknown;
  tool_calls: unknown[] | null;
  citations: CompanionCitation[];
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number | null;
  latency_ms: number | null;
  created_at: string;
}

export interface CompanionConversationDetail extends CompanionConversation {
  messages: CompanionMessage[];
}

export interface CompanionConversationList {
  chats: CompanionConversation[];
}

export type CompanionPlanStep = { title: string; status: string };

export type CompanionArtifact = {
  artifact_id: string;
  title: string;
  kind: string; // html | markdown | code
  content: string;
  language?: string;
};

export type CompanionWebCitation = {
  title: string;
  url: string;
  start_index?: number;
  end_index?: number;
};

export type CompanionEvent =
  | {
      type: "turn_start";
      message_id: string;
      conversation_id: string;
      assistant_message_id?: string;
      title?: string;
    }
  | { type: "thinking"; text: string }
  | { type: "tool_call"; call_id: string; tool: string; args: Record<string, unknown> }
  | { type: "tool_result"; call_id: string; summary: string; ok?: boolean }
  | { type: "plan"; steps: CompanionPlanStep[] }
  | {
      type: "artifact";
      artifact_id: string;
      title: string;
      kind: string;
      content: string;
      language?: string;
    }
  | { type: "web_citations"; citations: CompanionWebCitation[] }
  | { type: "token"; text: string }
  | {
      type: "citation";
      index: number;
      segment_id: string;
      recording_id: string;
      start_ms: number | null;
      end_ms: number | null;
      span_start: number;
      span_end: number;
    }
  | {
      type: "done";
      message_id: string;
      input_tokens: number | null;
      output_tokens: number | null;
      cached_tokens: number | null;
      model: string;
      latency_ms: number;
    }
  | { type: "memory_updated"; block: string; operation: string }
  | {
      type: "action_proposed";
      action_id: string;
      kind: string;
      tool: string;
      preview: string;
      expires_at: string;
      recipient: string | null;
    }
  | {
      type: "action_result";
      action_id: string;
      status: string;
      detail: string;
      undo_token: string | null;
    }
  | { type: "narration"; text: string }
  | {
      type: "desktop_action";
      action_id: string;
      command: Record<string, unknown>;
      device_target: string | null;
    }
  | { type: "error"; code: string; message: string };

export interface SharedRecording {
  id: string;
  title: string | null;
  type: RecordingType;
  duration_seconds: number | null;
  language: string | null;
  created_at: string;
  shared_at: string;
  segments: Segment[];
  summary: Summary | null;
  action_items: ActionItem[];
  highlights: Highlight[];
}

export interface SpeakerStat {
  name: string;
  total_duration_ms: number;
  percentage: number;
  segment_count: number;
  avg_segment_duration_ms: number;
  word_count: number;
  words_per_minute: number;
  first_spoke_ms: number;
  last_spoke_ms: number;
}

export interface SpeakerTimelineEntry {
  speaker: string;
  start_ms: number;
  end_ms: number;
}

export interface SpeakerStatsResponse {
  recording_id: string;
  total_duration_ms: number;
  total_speakers: number;
  speakers: SpeakerStat[];
  timeline: SpeakerTimelineEntry[];
}

export interface RelatedRecording {
  id: string;
  title: string | null;
  created_at: string;
  recording_type: string;
  similarity_score: number;
  matching_topic: string | null;
}

export interface RelatedRecordingsResponse {
  recording_id: string;
  related: RelatedRecording[];
}

export interface SearchResult {
  recording_id: string;
  recording_title: string | null;
  recording_type: string;
  segment_id: string;
  speaker: string | null;
  content: string;
  start_ms: number | null;
  end_ms: number | null;
  score: number;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
}

// --- Second brain: universal items, comparisons, unified search, ingestion ---

export interface UnifiedHit {
  source_kind: "recording" | "item";
  parent_id: string;
  chunk_id: string;
  title: string | null;
  kind: string;
  snippet: string;
  score: number;
  created_at: string | null;
}

export interface UnifiedSearchResponse {
  results: UnifiedHit[];
  total: number;
}

export interface ItemSummary {
  summary: string | null;
  key_points: unknown[] | null;
  action_items: unknown[] | null;
  topics: unknown[] | null;
  people_mentioned: unknown[] | null;
  highlights: unknown[] | null;
  key_moments: KeyMoment[] | null;
  sentiment: string | null;
}

export interface KeyMoment {
  timestamp: string | null;
  moment: string;
  why_it_matters: string;
  quote: string | null;
  importance: string;
  start_ms?: number | null;
  end_ms?: number | null;
}

export interface ItemError {
  code: string;
  message: string;
}

export type ItemStatus =
  | "fetching"
  | "summarizing"
  | "ready"
  | "needs_input"
  | "failed";

export interface Item {
  id: string;
  source: string;
  source_ref: string | null;
  url: string | null;
  kind: string;
  title: string | null;
  body: string | null;
  occurred_at: string | null;
  state: string;
  status: ItemStatus;
  error: ItemError | null;
  folder_id: string | null;
  created_at: string;
  summary: ItemSummary | null;
  summary_audio: SummaryAudio | null;
}

export interface ItemListEntry {
  id: string;
  source: string;
  url: string | null;
  kind: string;
  title: string | null;
  state: string;
  status: ItemStatus;
  error: ItemError | null;
  folder_id: string | null;
  occurred_at: string | null;
  created_at: string;
  has_summary: boolean;
}

export interface ItemListResponse {
  items: ItemListEntry[];
  total: number;
}

export interface SchemePosition {
  x: number;
  y: number;
}

export interface SchemeStrokePoint extends SchemePosition {
  pressure: number;
}

export interface SchemeViewport {
  x: number;
  y: number;
  zoom: number;
}

export interface SchemePresentationState {
  active: boolean;
  frame_id: string | null;
}

export type SchemeStrokeKind = "pen" | "highlighter";

export interface SchemeStroke {
  id: string;
  points: SchemeStrokePoint[];
  kind: SchemeStrokeKind;
  color: string;
  width: number;
  opacity: number;
  locked: boolean;
  z_index: number;
}

export interface SchemeCanvasCard {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  text: string;
  color: string;
  locked: boolean;
  z_index: number;
}

export type SchemeShapeKind = "rectangle" | "ellipse";

export interface SchemeCanvasShape {
  id: string;
  kind: SchemeShapeKind;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
  fill: string;
  locked: boolean;
  z_index: number;
}

export interface SchemeCanvasFrame {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  title: string;
  color: string;
  fill: string;
  locked: boolean;
  z_index: number;
}

export interface SchemeTextBlock {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  text: string;
  color: string;
  font_size: number;
  locked: boolean;
  z_index: number;
}

export type SchemeCanvasSourceKind = "item" | "recording" | "chat";

export interface SchemeCanvasSourceBlock {
  id: string;
  source_kind: SchemeCanvasSourceKind;
  source_id: string;
  citation_id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  title: string;
  subtitle: string | null;
  excerpt: string | null;
  color: string;
  locked: boolean;
  z_index: number;
}

export interface SchemeConnector {
  id: string;
  source_id: string | null;
  target_id: string | null;
  points: SchemePosition[];
  label: string | null;
  color: string;
  locked: boolean;
  z_index: number;
}

export interface SchemeCanvasComment {
  id: string;
  x: number;
  y: number;
  text: string;
  resolved: boolean;
}

export interface SchemeCanvasLayout {
  version: number;
  snap_to_grid: boolean;
  grid_size: number;
  viewport: SchemeViewport;
  presentation: SchemePresentationState;
  node_positions: Record<string, SchemePosition>;
  strokes: SchemeStroke[];
  cards: SchemeCanvasCard[];
  shapes: SchemeCanvasShape[];
  frames: SchemeCanvasFrame[];
  frame_order: string[];
  texts: SchemeTextBlock[];
  sources: SchemeCanvasSourceBlock[];
  connectors: SchemeConnector[];
  comments: SchemeCanvasComment[];
}

export interface SchemeNode {
  id: string;
  kind: string;
  title: string;
  body?: string | null;
  lane?: string | null;
  source_kind?: string;
  source_id?: string;
  entity_id?: string;
  entity_type?: string;
  citation_ids?: string[];
  position: SchemePosition;
}

export interface SchemeEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  label?: string | null;
  citation_ids?: string[];
}

export interface SchemeProjection {
  version: number;
  scheme_type: string;
  map_type?: string;
  title: string;
  prompt: string;
  summary: string;
  nodes: SchemeNode[];
  edges: SchemeEdge[];
  stats: Record<string, unknown>;
  briefing: Record<string, unknown> | null;
  citations: Array<Record<string, unknown>>;
  freshness: Record<string, unknown>;
}

export interface SchemeRevision {
  id: string;
  scheme_id: string;
  revision_index: number;
  projection: SchemeProjection;
  source_fingerprint: string;
  source_count: number;
  freshness: Record<string, unknown>;
  diff: Record<string, unknown>;
  citations: Array<Record<string, unknown>>;
  compiled_at: string;
  created_at: string;
}

export interface Scheme {
  id: string;
  space_id: string | null;
  title: string;
  prompt: string;
  scheme_type: string;
  origin: string;
  status: string;
  source_scope: Record<string, unknown> | null;
  layout: SchemeCanvasLayout | null;
  current_revision_id: string | null;
  current_revision: SchemeRevision | null;
  created_at: string;
  updated_at: string;
}

export interface SchemesResponse {
  schemes: Scheme[];
}

export interface ComparisonColumn {
  name: string;
  type: string;
}

export interface ComparisonRow {
  item_id: string;
  title: string;
  values: Record<string, string | number | boolean | null>;
  edited?: boolean;
}

export interface ComparisonSet {
  id: string;
  title: string | null;
  item_ids: string[];
  columns: ComparisonColumn[] | null;
  rows: ComparisonRow[] | null;
  schema_rationale: string | null;
  status: string;
  created_at: string;
}

export interface ComparisonListEntry {
  id: string;
  title: string | null;
  item_count: number;
  status: string;
  created_at: string;
}

export interface StarRecordingResponse {
  id: string;
  starred_at: string | null;
}

export interface TopicCount {
  topic: string;
  count: number;
}

export interface PersonCount {
  name: string;
  count: number;
}

export interface DigestActionItem {
  id: string;
  recording_id: string;
  recording_title: string | null;
  task: string;
  owner: string | null;
  priority: string | null;
  status: string;
}

export interface DigestHighlight {
  id: string;
  recording_id: string;
  recording_title: string | null;
  category: string;
  title: string;
  importance: string;
}

export interface DailyBreakdown {
  date: string;
  count: number;
  duration_seconds: number;
}

export interface WeekCount {
  week: string;
  count: number;
}

export interface AnalyticsResponse {
  total_recordings: number;
  total_duration_seconds: number;
  average_duration_seconds: number;
  total_words: number;
  by_type: Record<string, number>;
  by_week: WeekCount[];
}

export type BulkAction = "delete" | "restore" | "move";

export interface BulkOperationRequest {
  recording_ids: string[];
  action: BulkAction;
  folder_id?: string | null;
}

export interface BulkOperationResponse {
  processed: number;
  failed: number;
}

export interface KeywordItem {
  term: string;
  count: number;
}

export interface KeywordsResponse {
  recording_id: string;
  total_words: number;
  keywords: KeywordItem[];
}

export interface TranscriptStatsResponse {
  recording_id: string;
  segment_count: number;
  word_count: number;
  unique_speakers: number;
  speakers: string[];
  avg_words_per_segment: number;
  longest_segment_ms: number | null;
  shortest_segment_ms: number | null;
}

export interface TranscriptSearchMatch {
  segment_id: string;
  speaker: string | null;
  content: string;
  start_ms: number | null;
  end_ms: number | null;
  match_count: number;
}

export interface TranscriptSearchResponse {
  recording_id: string;
  query: string;
  total_matches: number;
  segments: TranscriptSearchMatch[];
}

export interface WeeklyDigestResponse {
  period_start: string;
  period_end: string;
  total_recordings: number;
  total_duration_seconds: number;
  recordings_by_type: Record<string, number>;
  top_topics: TopicCount[];
  top_people: PersonCount[];
  pending_action_items: DigestActionItem[];
  highlights: DigestHighlight[];
  sentiment_breakdown: Record<string, number>;
  daily_breakdown: DailyBreakdown[];
}



export interface RealtimeVoiceSession {
  provider: string;
  mode: RealtimeVoiceMode;
  agent_id: string;
  signed_url: string;
  expires_in_seconds: number;
  environment: string | null;
  branch_id: string | null;
}

export interface McpConnection {
  client_id: string;
  client_name: string;
  client_uri: string | null;
  scopes: string[];
  approved_at: string;
  last_active_at: string | null;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  last4: string;
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  token: string;
}

export interface Folder {
  id: string;
  name: string;
  created_at: string;
  // Recordings + materials filed in the folder (server-computed).
  item_count?: number;
}

export interface DictationEntry {
  client_entry_id: string;
  raw_text: string;
  cleaned_text: string | null;
  duration_seconds: number;
  word_count: number;
  occurred_at: string;
}

export interface DictationDictionaryWord {
  client_word_id: string;
  word: string;
  replacement: string | null;
  occurred_at: string;
}
