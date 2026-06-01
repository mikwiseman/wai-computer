export type RecordingType = "meeting" | "note" | "reflection";
export type ActionStatus = "pending" | "in_progress" | "completed" | "cancelled";
export type ActionPriority = "high" | "medium" | "low";
export type EntityType = "person" | "organization" | "project" | "topic";
export type ExportFormat = "markdown" | "txt" | "srt";
export type ExportLocale = "en" | "ru";
export type RealtimeVoiceMode = "conversation" | "recording";

export type SummaryStyle = "brief" | "medium" | "detailed";

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
  dictation_post_filter_provider: string;
  dictation_post_filter_model: string;
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
  action_items: ActionItem[];
  highlights: Highlight[];
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

export type CompanionEvent =
  | { type: "turn_start"; message_id: string; conversation_id: string }
  | { type: "tool_call"; call_id: string; tool: string; args: Record<string, unknown> }
  | { type: "tool_result"; call_id: string; summary: string }
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
  folder_id: string | null;
  created_at: string;
  summary: ItemSummary | null;
}

export interface ItemListEntry {
  id: string;
  source: string;
  url: string | null;
  kind: string;
  title: string | null;
  state: string;
  folder_id: string | null;
  occurred_at: string | null;
  created_at: string;
  has_summary: boolean;
}

export interface ItemListResponse {
  items: ItemListEntry[];
  total: number;
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

export interface McpIngestionConnection {
  id: string;
  server_label: string;
  server_url: string;
  transport: string;
  auth_type: string;
  has_token: boolean;
  allowed_tools: string[] | null;
  capabilities: Record<string, unknown> | null;
  privacy_level: string;
  sync_interval_minutes: number;
  status: string;
  enabled: boolean;
  last_sync_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface Entity {
  id: string;
  type: EntityType;
  name: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface EntityDetail extends Entity {
  relations: Array<{
    id: string;
    target_id: string;
    target_type: EntityType;
    target_name: string;
    relation_type: string | null;
    context: string | null;
  }>;
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
