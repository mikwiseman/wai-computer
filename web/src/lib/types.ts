export type RecordingType = "meeting" | "note" | "reflection";
export type ActionStatus = "pending" | "in_progress" | "completed" | "cancelled";
export type ActionPriority = "high" | "medium" | "low";
export type EntityType = "person" | "organization" | "project" | "topic";
export type ExportFormat = "markdown" | "txt" | "srt";

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
  content: string;
  start_ms: number | null;
  end_ms: number | null;
  confidence: number | null;
}

export interface Summary {
  summary: string | null;
  key_points: string[] | null;
  decisions: Array<Record<string, unknown>> | null;
  topics: string[] | null;
  people_mentioned: string[] | null;
  sentiment: string | null;
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

export interface ChatSource {
  segment_id: string;
  recording_id: string;
  recording_title: string | null;
  speaker: string | null;
  content: string;
  start_ms: number | null;
  end_ms: number | null;
}

export interface ChatResponse {
  answer: string;
  session_id: string;
  message_id: string;
  sources: ChatSource[];
}

export interface ChatMessageData {
  id: string;
  role: "user" | "assistant";
  content: string;
  source_segment_ids: string[] | null;
  source_recording_ids: string[] | null;
  created_at: string;
}

export interface ChatSession {
  id: string;
  title: string | null;
  recording_ids: string[] | null;
  created_at: string;
  message_count: number;
  pinned_at: string | null;
}

export interface PinSessionResponse {
  id: string;
  pinned_at: string | null;
}

export interface StarRecordingResponse {
  id: string;
  starred_at: string | null;
}

export interface ChatSessionDetail {
  id: string;
  title: string | null;
  recording_ids: string[] | null;
  created_at: string;
  messages: ChatMessageData[];
}

export interface RenameSessionResponse {
  id: string;
  title: string | null;
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

// ── Agent Chat ──────────────────────────────────────────────────────

export interface AgentChatRequest {
  message: string;
  session_id?: string;
  voice_transcript?: string;
}

export interface AgentChatResponse {
  response: string;
  intent: string;
  model_used: string;
  session_id: string;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
}

// ── User Apps (Collections) ─────────────────────────────────────────

export interface UserApp {
  id: string;
  name: string;
  display_name: string;
  icon: string | null;
  template: string | null;
  schema_def: Record<string, unknown> | null;
  app_url: string | null;
  settings: Record<string, unknown> | null;
  sort_order: number;
  item_count: number;
  created_at: string;
}

export interface AppItem {
  id: string;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AppStats {
  app_id: string;
  total_items: number;
  created_at: string;
  last_item_at: string | null;
}

// ── Digital Agents ──────────────────────────────────────────────────

export interface DigitalAgent {
  id: string;
  name: string;
  description: string;
  schedule_type: string;
  cron_expression: string | null;
  status: string;
  delivery_channel: string;
  run_count: number;
  error_count: number;
  last_run_at: string | null;
  next_run_at: string | null;
  last_result: string | null;
  last_error: string | null;
  created_at: string;
}
