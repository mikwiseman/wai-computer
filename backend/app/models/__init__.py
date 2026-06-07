"""SQLAlchemy models."""

from app.models.admin import AdminAuditLog, AdminRole, StaffMember
from app.models.agent import Agent, AgentRun, AgentStep
from app.models.ai_usage import AiUsageEvent
from app.models.api_key import ApiKey
from app.models.base import Base
from app.models.benchmark import DictationBenchmarkVote
from app.models.billing import (
    BillingEvent,
    BillingPeriod,
    BillingPromoCode,
    BillingPromoRedemption,
    BillingProvider,
    Invoice,
    Plan,
    PlanCode,
    Subscription,
    SubscriptionStatus,
    UsageWeek,
)
from app.models.brain_map import BrainMap, BrainMapRevision
from app.models.brain_space import (
    BrainClaim,
    BrainPage,
    BrainReviewPack,
    BrainSpace,
    BrainSpaceMember,
    BrainSpaceSource,
)
from app.models.commitment import Commitment
from app.models.companion import (
    ChatMessage,
    Conversation,
    ConversationChunk,
    MessageCitation,
)
from app.models.companion_pending_action import CompanionPendingAction
from app.models.comparison import ComparisonSet
from app.models.deepgram_usage import DeepgramUsageEvent
from app.models.device import Device
from app.models.dictation import DictationDictionaryWord, DictationEntry
from app.models.entity import (
    Entity,
    EntityMention,
    EntityPageSnapshot,
    EntityRelation,
    RecordingTag,
    Tag,
)
from app.models.highlight import Highlight
from app.models.item import Item, ItemChunk, ItemSummary
from app.models.mcp_connection import McpConnection, McpIngestionRun
from app.models.mcp_oauth import (
    McpOAuthAuthorizationCode,
    McpOAuthAuthorizationRequest,
    McpOAuthClient,
    McpOAuthConsent,
    McpOAuthToken,
)
from app.models.memory_proposal import MemoryProposal
from app.models.person import (
    Person,
    PublicVoiceprint,
    RecordingSpeakerEmbedding,
    Voiceprint,
)
from app.models.personalization import PersonalizationImportJob, PersonalizationTerm
from app.models.recording import (
    ActionItem,
    Folder,
    Recording,
    RecordingShare,
    Segment,
    Summary,
    SummaryGenerationJob,
    SummaryGenerationStatus,
)
from app.models.refresh_token import RefreshToken
from app.models.reminder import UserReminder
from app.models.summary_audio import SummaryAudioArtifact, SummaryAudioStatus
from app.models.telegram import (
    TelegramAccount,
    TelegramBotLinkCode,
    TelegramPairing,
    TelegramUpdate,
)
from app.models.user import User
from app.models.user_memory import UserMemoryBlock, UserMemoryLogEntry

__all__ = [
    "Base",
    "ApiKey",
    "Agent",
    "AgentRun",
    "AgentStep",
    "AdminAuditLog",
    "AdminRole",
    "StaffMember",
    "DictationBenchmarkVote",
    "BillingEvent",
    "BillingPeriod",
    "BillingPromoCode",
    "BillingPromoRedemption",
    "BillingProvider",
    "Invoice",
    "Plan",
    "PlanCode",
    "Subscription",
    "SubscriptionStatus",
    "UsageWeek",
    "BrainClaim",
    "BrainMap",
    "BrainMapRevision",
    "BrainPage",
    "BrainReviewPack",
    "BrainSpace",
    "BrainSpaceMember",
    "BrainSpaceSource",
    "User",
    "Recording",
    "RecordingShare",
    "Folder",
    "Segment",
    "Summary",
    "SummaryGenerationJob",
    "SummaryGenerationStatus",
    "SummaryAudioArtifact",
    "SummaryAudioStatus",
    "ActionItem",
    "Highlight",
    "Item",
    "ItemChunk",
    "ItemSummary",
    "ComparisonSet",
    "McpConnection",
    "McpIngestionRun",
    "MemoryProposal",
    "Person",
    "PublicVoiceprint",
    "RecordingSpeakerEmbedding",
    "Voiceprint",
    "PersonalizationImportJob",
    "PersonalizationTerm",
    "Entity",
    "EntityRelation",
    "Tag",
    "RecordingTag",
    "RefreshToken",
    "UserReminder",
    "TelegramAccount",
    "TelegramBotLinkCode",
    "TelegramPairing",
    "TelegramUpdate",
    "Commitment",
    "Conversation",
    "ChatMessage",
    "ConversationChunk",
    "MessageCitation",
    "CompanionPendingAction",
    "Device",
    "DictationEntry",
    "DictationDictionaryWord",
    "AiUsageEvent",
    "DeepgramUsageEvent",
    "McpOAuthClient",
    "McpOAuthAuthorizationRequest",
    "McpOAuthAuthorizationCode",
    "McpOAuthToken",
    "McpOAuthConsent",
    "UserMemoryBlock",
    "UserMemoryLogEntry",
    "EntityMention",
    "EntityPageSnapshot",
]
