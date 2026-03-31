// WaiComputerKit - Shared code for WaiComputer iOS and macOS apps

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
public typealias WKChatResponse = ChatResponse
public typealias WKChatSource = ChatSource
public typealias WKChatSessionListItem = ChatSessionListItem
public typealias WKChatSessionDetail = ChatSessionDetail
public typealias WKChatMessageResponse = ChatMessageResponse

// Agent models
public typealias WKAgentChatResponse = AgentChatResponse
public typealias WKDigitalAgent = DigitalAgent
public typealias WKAgentRunResponse = AgentRunResponse

// App models
public typealias WKJSONValue = JSONValue
public typealias WKUserApp = UserApp
public typealias WKAppItem = AppItem
public typealias WKAppStats = AppStats
