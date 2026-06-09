"""Starter RU+EN golden set for the accuracy-per-dollar eval (P0·eval).

A seed set — grow it from real prod queries. Each entry plants a source and a
query that should retrieve it; DISTRACTORS are unrelated sources retrieval must
not confuse it with. RU + EN so we never tune on English alone.
"""

from tests.eval.brain_eval import GoldenQuery

GOLDEN: list[GoldenQuery] = [
    GoldenQuery(
        id="budget-en", lang="en",
        query="what did we decide about the quarterly budget?",
        expected=["quarterly budget"],
        seed_title="Q3 Budget Meeting",
        seed_body="We approved the quarterly budget and capped marketing at 20 percent.",
    ),
    GoldenQuery(
        id="budget-ru", lang="ru",
        query="что мы решили по поводу квартального бюджета?",
        expected=["бюджет"],
        seed_title="Совещание по бюджету",
        seed_body="Мы утвердили квартальный бюджет и ограничили маркетинг двадцатью процентами.",
    ),
    GoldenQuery(
        id="vendor-en", lang="en",
        query="which vendor did we pick for hosting?",
        expected=["hetzner"],
        seed_title="Hosting decision",
        seed_body="After comparing options we chose Hetzner for the backend hosting.",
    ),
    GoldenQuery(
        id="allergy-en", lang="en",
        query="do I have any medical allergies?",
        expected=["penicillin"],
        seed_title="Health note",
        seed_body="Important: I am allergic to penicillin.",
    ),
    GoldenQuery(
        id="standup-ru", lang="ru",
        query="когда у нас ежедневный созвон команды?",
        expected=["созвон", "10:00"],
        seed_title="Расписание команды",
        seed_body="Ежедневный созвон команды в 10:00 по будням.",
    ),
    GoldenQuery(
        id="launch-en", lang="en",
        query="when is the product launch?",
        expected=["september", "launch"],
        seed_title="Launch plan",
        seed_body="The product launch is scheduled for September 15th.",
    ),
    GoldenQuery(
        id="contract-ru", lang="ru",
        query="на какой срок подписан контракт с Acme?",
        expected=["acme", "год"],
        seed_title="Контракт Acme",
        seed_body="Контракт с Acme подписан на один год с правом продления.",
    ),
    GoldenQuery(
        id="auth-en", lang="en",
        query="how does login work on the web app?",
        expected=["cookie", "auth"],
        seed_title="Web auth notes",
        seed_body="Web login depends on the auth cookie domain being set correctly.",
    ),
]

DISTRACTORS: list[tuple[str, str]] = [
    ("Lunch order", "Team lunch was pizza and salad on Friday."),
    ("Vacation", "I will be on vacation the last week of August."),
    ("Книга", "Дочитал книгу про продуктивность, понравилась глава про привычки."),
    ("Gym", "Switched my workout to mornings, three times a week."),
    ("Погода", "На выходных обещают дождь, надо взять зонт."),
    ("Music", "Made a new ambient playlist for focus work."),
]
