"""Unit tests for zero-LLM structured entity extraction + the mint gate."""

from app.core.mcp_entity_extract import extract_graph


def _by_type(graph, type_):
    return [e for e in graph.entities if e.type == type_]


def _names(graph, type_):
    return {e.name for e in _by_type(graph, type_)}


# ── email ───────────────────────────────────────────────────────────────────
def test_email_extracts_sender_recipient_and_subject():
    meta = {
        "from": "Mik Wiseman <mik@example.com>",
        "to": "Bob <bob@acme.com>",
        "subject": "Re: Q3 launch",
    }
    g = extract_graph("email", meta)
    people = {(e.name, e.identity_key, e.role) for e in _by_type(g, "person")}
    assert ("Mik Wiseman", "mik@example.com", "sender") in people
    assert ("Bob", "bob@acme.com", "recipient") in people
    # Subject is the thread-clustering topic, Re:/Fwd: stripped.
    assert "Q3 launch" in _names(g, "topic")


def test_email_suppresses_automated_sender_keeps_subject():
    meta = {"from": "noreply@example.com", "subject": "Your receipt"}
    g = extract_graph("email", meta)
    assert _by_type(g, "person") == []
    assert "Your receipt" in _names(g, "topic")


def test_email_bulk_marker_suppresses_people():
    meta = {
        "from": "Real Person <real@person.com>",
        "subject": "Weekly digest",
        "list-unsubscribe": "<mailto:unsub@x.com>",
    }
    g = extract_graph("email", meta)
    assert _by_type(g, "person") == []  # bulk: no people minted
    assert "Weekly digest" in _names(g, "topic")


def test_email_large_recipient_list_keeps_sender_drops_recipients():
    meta = {
        "from": "Sender <s@x.com>",
        "to": [f"p{i}@x.com" for i in range(10)],
        "subject": "All hands",
    }
    g = extract_graph("email", meta)
    people = {e.identity_key for e in _by_type(g, "person")}
    assert people == {"s@x.com"}  # only the sender; 10 recipients suppressed


def test_email_dict_addresses():
    meta = {
        "from": {"name": "Ann", "email": "ANN@X.com"},
        "to": [{"email": "z@x.com", "name": "Zed"}],
        "subject": "hi",
    }
    g = extract_graph("email", meta)
    keys = {e.identity_key for e in _by_type(g, "person")}
    assert keys == {"ann@x.com", "z@x.com"}  # lowercased


# ── event ─────────────────────────────────────────────────────────────────
def test_event_extracts_organizer_attendees_title():
    meta = {
        "summary": "Design sync",
        "organizer": {"email": "lead@x.com", "displayName": "Lead"},
        "attendees": [{"email": "a@x.com"}, {"email": "b@x.com"}],
    }
    g = extract_graph("event", meta)
    assert "Design sync" in _names(g, "topic")
    keys = {e.identity_key for e in _by_type(g, "person")}
    assert keys == {"lead@x.com", "a@x.com", "b@x.com"}


# ── note ──────────────────────────────────────────────────────────────────
def test_note_extracts_tags_wikilinks_title():
    meta = {
        "title": "Project Atlas",
        "tags": ["#roadmap", "planning"],
        "content": "See [[Q3 launch]] and [[Bob Smith|Bob]] for details.",
    }
    g = extract_graph("note", meta)
    topics = _names(g, "topic")
    assert {"Project Atlas", "roadmap", "planning", "Q3 launch", "Bob Smith"} <= topics


# ── message ────────────────────────────────────────────────────────────────
def test_message_extracts_sender_and_mentions():
    meta = {
        "from": {"first_name": "Kate", "username": "kate_w"},
        "text": "ping @rob_dev about the deploy",
    }
    g = extract_graph("message", meta)
    people = {(e.name, e.identity_key) for e in _by_type(g, "person")}
    assert ("Kate", "@kate_w") in people
    assert ("rob_dev", "@rob_dev") in people


# ── unknown kind / non-dict ────────────────────────────────────────────────
def test_unknown_kind_and_non_dict_are_empty():
    assert extract_graph("transaction", {"x": 1}).entities == []
    assert extract_graph("email", None).entities == []
    assert extract_graph("email", "not a dict").entities == []
