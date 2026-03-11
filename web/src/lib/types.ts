export type RecordingType = "meeting" | "note" | "reflection";
export type ActionStatus = "pending" | "in_progress" | "completed" | "cancelled";
export type ActionPriority = "high" | "medium" | "low";
export type EntityType = "person" | "organization" | "project" | "topic";
export type ExportFormat = "markdown" | "txt" | "srt";

export interface TokenResponse {
  access_token: string;
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
  duration_seconds: number | null;
  language: string | null;
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
}

export interface ChatSessionDetail {
  id: string;
  title: string | null;
  recording_ids: string[] | null;
  created_at: string;
  messages: ChatMessageData[];
}
