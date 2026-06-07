"""Zero-LLM structured entity extraction from a synced item's raw record.

MCP items defer per-item LLM summaries (a 100k-message mailbox must not trigger
100k summaries), so ``seed_entities_from_summary`` will not fire for most of
them. This module makes them graph citizens anyway: it reads the structured
fields already in ``Item.metadata_`` (the raw tool record) — email From/To/Cc,
calendar attendees, Notion/Obsidian tags + ``[[wikilinks]]`` — and emits people
and topics to mention, with **no LLM and no network**.

The mint gate is the load-bearing part at mailbox scale: a mailbox has thousands
of one-off ``no-reply@`` / newsletter senders, and minting an entity for each
would flood the graph and wreck dossiers. So we mint a *person* only when it is
real signal (a non-automated sender; recipients on a small thread); the email is
**always** ingested + searchable regardless — suppression means "no node", never
"no data". Topics from author-curated tags/wikilinks are minted directly.

Pure (no I/O) -> exhaustively unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email.utils import getaddresses, parseaddr
from typing import Any

# Local-parts that are machines/lists, never a person.
AUTOMATED_LOCALPARTS: frozenset[str] = frozenset(
    {
        "no-reply", "noreply", "donotreply", "do-not-reply", "do_not_reply",
        "notifications", "notification", "notify", "mailer-daemon", "postmaster",
        "bounce", "bounces", "support", "help", "info", "hello", "team",
        "newsletter", "news", "updates", "update", "alerts", "alert", "billing",
        "receipts", "receipt", "sales", "marketing", "automated", "auto",
        "system", "root", "admin", "mail", "email", "account", "accounts",
        "security", "service", "noreply-dev", "feedback", "contact",
    }
)
_AUTOMATED_RE = re.compile(r"(^|[._-])(bot|daemon|mailer|noreply|no-reply|notify)([._-]|$)", re.I)
_WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:[#|][^\]]*)?\]\]")
_SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fwd|fw|aw|ответ|пересл)\s*:\s*", re.I)

SMALL_RECIPIENT_MAX = 5     # threads with <= this many recipients mint recipients
MAX_TOPICS_PER_ITEM = 20
MAX_TAG_LEN = 80
MAX_ATTENDEES = 25


@dataclass
class ExtractedEntity:
    type: str               # "person" | "topic"
    name: str
    identity_key: str | None = None   # email / handle for people; None for topics
    role: str | None = None           # mention context: sender|recipient|attendee|tag|...


@dataclass
class ExtractedGraph:
    entities: list[ExtractedEntity] = field(default_factory=list)


class ExtractorShapeError(Exception):
    """A record's metadata had a shape an extractor expected but couldn't parse.

    Raised (not silently swallowed) so a provider format change surfaces as a
    visible ``extract_errors`` count rather than the graph quietly not growing.
    """


# ── small helpers (case-tolerant access into a raw record) ──────────────────
def _get(meta: dict, *keys: str) -> Any:
    lowered = {k.lower(): v for k, v in meta.items()} if isinstance(meta, dict) else {}
    for key in keys:
        if key in meta:
            return meta[key]
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _is_automated(email: str | None) -> bool:
    if not email or "@" not in email:
        return True
    local = email.split("@", 1)[0].lower()
    if local in AUTOMATED_LOCALPARTS:
        return True
    return bool(_AUTOMATED_RE.search(local))


def _is_bulk(meta: dict) -> bool:
    """List/bulk/automated mail markers — suppress people from these entirely."""
    if _get(meta, "list-unsubscribe", "list_unsubscribe", "list-id", "list_id"):
        return True
    precedence = _get(meta, "precedence")
    if isinstance(precedence, str) and precedence.lower() in {"bulk", "list", "auto_reply", "junk"}:
        return True
    auto = _get(meta, "auto-submitted", "auto_submitted")
    if isinstance(auto, str) and auto.lower() != "no":
        return True
    headers = _get(meta, "headers")
    if isinstance(headers, dict) and _is_bulk(headers):
        return True
    return False


def _parse_one(value: Any) -> tuple[str | None, str | None]:
    """Return (display_name, email) from a string or dict address."""
    if value is None:
        return None, None
    if isinstance(value, dict):
        email = value.get("email") or value.get("address") or value.get("emailAddress")
        name = value.get("name") or value.get("displayName") or value.get("display_name")
        return (name or None), (email.lower() if isinstance(email, str) else None)
    if isinstance(value, str):
        name, addr = parseaddr(value)
        return (name or None), (addr.lower() if addr and "@" in addr else None)
    return None, None


def _parse_list(value: Any) -> list[tuple[str | None, str | None]]:
    if value is None:
        return []
    if isinstance(value, str):
        return [(n or None, a.lower()) for n, a in getaddresses([value]) if a and "@" in a]
    if isinstance(value, dict):
        one = _parse_one(value)
        return [one] if one[1] else []
    if isinstance(value, list):
        out: list[tuple[str | None, str | None]] = []
        for v in value:
            n, a = _parse_one(v)
            if a:
                out.append((n, a))
        return out
    return []


def _person(name: str | None, email: str | None, role: str) -> ExtractedEntity | None:
    if email and _is_automated(email):
        return None
    display = (name or (email.split("@", 1)[0] if email else "")).strip()
    if not display:
        return None
    return ExtractedEntity("person", display, identity_key=email, role=role)


def _topic(name: str | None, role: str) -> ExtractedEntity | None:
    if not isinstance(name, str):
        return None
    clean = name.strip()
    if not clean or len(clean) > MAX_TAG_LEN:
        return None
    return ExtractedEntity("topic", clean, role=role)


def _clean_subject(subject: str) -> str:
    prev = None
    out = subject
    while prev != out:
        prev = out
        out = _SUBJECT_PREFIX_RE.sub("", out)
    return out.strip()


# ── per-kind extractors ─────────────────────────────────────────────────────
def _extract_email(meta: dict) -> ExtractedGraph:
    ents: list[ExtractedEntity] = []
    subject = _get(meta, "subject")
    if isinstance(subject, str) and subject.strip():
        topic = _topic(_clean_subject(subject), "subject")  # subject clusters the thread
        if topic:
            ents.append(topic)
    if _is_bulk(meta):
        return ExtractedGraph(ents)  # bulk: keep the topic, suppress people
    sender = _person(*_parse_one(_get(meta, "from", "sender", "fromAddress")), role="sender")
    if sender:
        ents.append(sender)
    recipients = _parse_list(_get(meta, "to")) + _parse_list(_get(meta, "cc"))
    if len(recipients) <= SMALL_RECIPIENT_MAX:
        for name, email in recipients:
            person = _person(name, email, "recipient")
            if person:
                ents.append(person)
    return ExtractedGraph(ents)


def _extract_event(meta: dict) -> ExtractedGraph:
    ents: list[ExtractedEntity] = []
    title = _get(meta, "summary", "title", "name")
    topic = _topic(title if isinstance(title, str) else None, "event")
    if topic:
        ents.append(topic)
    organizer = _person(*_parse_one(_get(meta, "organizer", "creator")), role="organizer")
    if organizer:
        ents.append(organizer)
    attendees = _parse_list(_get(meta, "attendees", "participants"))[:MAX_ATTENDEES]
    for name, email in attendees:
        person = _person(name, email, "attendee")  # invited => a real person, no gate
        if person:
            ents.append(person)
    return ExtractedGraph(ents)


def _extract_message(meta: dict) -> ExtractedGraph:
    ents: list[ExtractedEntity] = []
    sender = _get(meta, "from", "sender", "author")
    name = email = handle = None
    if isinstance(sender, dict):
        name = sender.get("first_name") or sender.get("name") or sender.get("username")
        handle = sender.get("username") or sender.get("handle")
        email = sender.get("email")
    elif isinstance(sender, str):
        name = sender
    key = (email or (f"@{handle}" if handle else None))
    if name or key:
        display = (name or key or "").strip() or (key or "")
        if display:
            ents.append(ExtractedEntity("person", display, identity_key=key, role="sender"))
    text = _get(meta, "text", "message", "body")
    if isinstance(text, str):
        for handle_match in set(re.findall(r"@([A-Za-z0-9_]{3,32})", text)):
            ents.append(
                ExtractedEntity(
                    "person", handle_match, identity_key=f"@{handle_match}", role="mention"
                )
            )
    return ExtractedGraph(ents)


def _extract_note(meta: dict) -> ExtractedGraph:
    ents: list[ExtractedEntity] = []
    title = _get(meta, "title", "name", "basename")
    topic = _topic(title if isinstance(title, str) else None, "title")
    if topic:
        ents.append(topic)
    tags = _get(meta, "tags")
    fm = _get(meta, "frontmatter", "properties")
    if isinstance(fm, dict) and not tags:
        tags = fm.get("tags")
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[\s,]+", tags) if t]
    if isinstance(tags, list):
        for tag in tags[:MAX_TOPICS_PER_ITEM]:
            label = tag.lstrip("#") if isinstance(tag, str) else None
            topic = _topic(label, "tag")
            if topic:
                ents.append(topic)
    body = _get(meta, "content", "text", "body", "markdown")
    if isinstance(body, str):
        for target in list(dict.fromkeys(_WIKILINK_RE.findall(body)))[:MAX_TOPICS_PER_ITEM]:
            topic = _topic(target, "wikilink")
            if topic:
                ents.append(topic)
    return ExtractedGraph(ents)


def _extract_file(meta: dict) -> ExtractedGraph:
    ents: list[ExtractedEntity] = []
    name = _get(meta, "name", "title", "filename")
    topic = _topic(name if isinstance(name, str) else None, "file")
    if topic:
        ents.append(topic)
    for owner in _parse_list(_get(meta, "owners", "owner")):
        person = _person(owner[0], owner[1], "owner")
        if person:
            ents.append(person)
    perms = _get(meta, "permissions", "sharing")
    if isinstance(perms, list):
        for p in perms[:MAX_ATTENDEES]:
            person = _person(*_parse_one(p), role="shared_with")
            if person:
                ents.append(person)
    return ExtractedGraph(ents)


_EXTRACTORS = {
    "email": _extract_email,
    "event": _extract_event,
    "message": _extract_message,
    "note": _extract_note,
    "file": _extract_file,
}


def extract_graph(kind: str, metadata: Any) -> ExtractedGraph:
    """Dispatch to the per-kind extractor. Unknown kind -> empty (no error)."""
    if not isinstance(metadata, dict):
        return ExtractedGraph([])
    fn = _EXTRACTORS.get(kind)
    if fn is None:
        return ExtractedGraph([])
    return fn(metadata)
