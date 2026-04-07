// WaiSayKit - Shared code for WaiSay iOS and macOS apps

@_exported import Foundation

// Re-export all public types
public typealias WKUser = User
public typealias WKRecording = Recording
public typealias WKRecordingDetail = RecordingDetail
public typealias WKFolder = Folder
public typealias WKSegment = Segment
public typealias WKSummary = Summary
public typealias WKActionItem = ActionItem
public typealias WKEntity = Entity
public typealias WKSearchResult = SearchResult
public typealias WKAPIClient = APIClient
public typealias WKWebSocketManager = WebSocketManager
public typealias WKMicrophoneCapture = MicrophoneCapture
public typealias WKAudioEncoder = AudioEncoder
public typealias WKQAResponse = QAResponse
public typealias WKQASource = QASource
public typealias WKRealtimeVoiceMode = RealtimeVoiceMode
public typealias WKRealtimeTranscriptionSessionConfig = RealtimeTranscriptionSessionConfig
public typealias WKRealtimeVoiceSession = RealtimeVoiceSession

// App models
public typealias WKJSONValue = JSONValue
public typealias WKAppStatus = AppStatus
public typealias WKAppVisibility = AppVisibility
public typealias WKUserApp = UserApp
public typealias WKAppItem = AppItem
public typealias WKAppStats = AppStats
