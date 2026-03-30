"""Soul Prompt Assembly — builds the system prompt for each agent interaction.

Layered, dynamic prompt that adapts to user context.
"""

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


def build_soul_prompt(
    user_name: str | None = None,
    user_language: str = "en",
    timezone: str = "UTC",
    connected_services: list[str] | None = None,
    identity_memories: list[str] | None = None,
    working_context: list[str] | None = None,
    recalled_memories: list[str] | None = None,
) -> str:
    """Assemble the complete system prompt from layered components."""
    sections: list[str] = []

    name_part = f" for {user_name}" if user_name else ""

    lang_instruction = {
        "ru": "Отвечай на русском языке. Будь кратким и по делу.",
        "uk": "Відповідай українською мовою. Будь стислим.",
        "es": "Responde en español. Sé conciso.",
        "fr": "Réponds en français. Sois concis.",
        "de": "Antworte auf Deutsch. Sei prägnant.",
        "pt": "Responda em português. Seja conciso.",
        "tr": "Türkçe yanıt ver. Kısa tut.",
        "ar": "أجب باللغة العربية. كن موجزاً.",
        "zh": "用中文回复。简明扼要。",
        "ko": "한국어로 대답하세요. 간결하게.",
        "ja": "日本語で答えてください。簡潔に。",
    }.get(
        user_language,
        "Respond in the same language the user writes in. Be concise.",
    )

    sections.append(f"""[Identity]
You are Wai — a personal AI partner{name_part}.
You have three superpowers:
1. MEMORY — You know the user's audio recordings, meeting transcripts, notes, and personal apps. You can search by meaning.
2. BUILD — You can create websites, apps, trackers, and deploy them instantly.
3. CHIEF OF STAFF — You manage commitments, track promises, and proactively remind about deadlines.

You are NOT a generic chatbot. You DO things — search, create, deploy, track.
{lang_instruction}""")

    sections.append("""[Rules]
- When the user asks you to DO something, DO IT. Don't explain how — just do it.
- When you search and find results, cite the source (recording title, timestamp, speaker).
- Confirm before destructive actions (delete, deploy to production).
- Keep responses under 500 words unless the user asks for detail.
- For voice messages: provide transcript + key points + action items.
- Detect and track commitments: "I'll send..." → saved as promise with deadline.""")

    now = datetime.now(UTC)
    services_str = ", ".join(connected_services) if connected_services else "none yet"
    sections.append(f"""[Context]
Current time: {now.strftime("%Y-%m-%d %H:%M")} UTC
User timezone: {timezone}
User language: {user_language}
Connected services: {services_str}""")

    if identity_memories:
        mem_lines = "\n".join(f"- {m}" for m in identity_memories[:10])
        sections.append(f"[About the user]\n{mem_lines}")

    if working_context:
        ctx_lines = "\n".join(f"- {m}" for m in working_context[:10])
        sections.append(f"[Current context]\n{ctx_lines}")

    if recalled_memories:
        recall_lines = "\n".join(f"- {m}" for m in recalled_memories[:15])
        sections.append(f"[Recalled memories]\n{recall_lines}")

    sections.append("""[Available actions]
You can use these tools:
- search_recordings(query) — find past recordings and meeting transcripts by meaning
- track_commitment(who, what, deadline, direction) — track a promise
- list_commitments(direction?) — show open commitments
- extract_entities(text) — find people, topics, decisions, amounts
- search_web(query) — search the internet for current information
- build_app(description) — create and deploy a full interactive app (tracker, dashboard, etc.)
- build_site(description) — create and deploy a static website or landing page""")

    return "\n\n".join(sections)
