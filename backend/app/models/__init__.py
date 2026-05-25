"""SQLAlchemy models."""

from app.models.admin import AdminAuditLog, AdminRole
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
from app.models.commitment import Commitment
from app.models.companion import ChatMessage, Conversation, MessageCitation
from app.models.dictation import DictationDictionaryWord, DictationEntry
from app.models.entity import Entity, EntityRelation, RecordingTag, Tag
from app.models.highlight import Highlight
from app.models.mcp_oauth import (
    McpOAuthAuthorizationCode,
    McpOAuthAuthorizationRequest,
    McpOAuthClient,
    McpOAuthConsent,
    McpOAuthToken,
)
from app.models.person import Person, Voiceprint
from app.models.recording import (
    ActionItem,
    Folder,
    Recording,
    RecordingShare,
    Segment,
    Summary,
)
from app.models.refresh_token import RefreshToken
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
    "AdminAuditLog",
    "AdminRole",
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
    "User",
    "Recording",
    "RecordingShare",
    "Folder",
    "Segment",
    "Summary",
    "ActionItem",
    "Highlight",
    "Person",
    "Voiceprint",
    "Entity",
    "EntityRelation",
    "Tag",
    "RecordingTag",
    "RefreshToken",
    "TelegramAccount",
    "TelegramBotLinkCode",
    "TelegramPairing",
    "TelegramUpdate",
    "Commitment",
    "Conversation",
    "ChatMessage",
    "MessageCitation",
    "DictationEntry",
    "DictationDictionaryWord",
    "McpOAuthClient",
    "McpOAuthAuthorizationRequest",
    "McpOAuthAuthorizationCode",
    "McpOAuthToken",
    "McpOAuthConsent",
    "UserMemoryBlock",
    "UserMemoryLogEntry",
]
