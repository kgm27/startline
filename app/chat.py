"""Natural-language question answering over the site's own player data.

The whole point of StartLine is that every number traces back to a real market,
so the assistant is never allowed to recall a number from training. Name
resolution and answer composition are deliberately split into two model
calls with a validation guardrail between them:

1. Resolve: given the question and the list of every active skill-position
   player's name, the model returns ONLY canonical names it's confident the
   question refers to (a nickname like "CMC" and a suffix mismatch like
   "Kenneth Walker" are both fine here — that's what this step is for).
2. Validate: every returned name must exact-match a real player after
   normalization (see app/name_utils.py). A name that doesn't validate is
   dropped rather than trusted — this is what keeps a hallucinated or
   near-miss resolution from silently pulling the wrong player's data.
3. Answer: the model gets the question plus the *validated* players' real
   numbers (pulled from our own data by player ID, not from the model) and
   is told to answer only from what it's given.

The model never supplies a stat, line, or projection from its own knowledge
at any stage — stage 1 only ever returns names, stage 3 only ever restates
numbers we hand it.

Cost control is a first-class concern here: this is a public endpoint that
spends real money, so both calls use the cheap model and the caller is
expected to enforce a per-IP rate limit and a daily budget.
"""
from __future__ import annotations  # this project runs Python 3.9; `X | None` needs 3.10

import logging
import os
from typing import Callable, Optional

from rapidfuzz import process as fuzz_process

from app.name_utils import normalize_name

MODEL = "claude-haiku-4-5"

MAX_TOKENS = 1024
MAX_QUESTION_CHARS = 500
RESOLVE_MAX_TOKENS = 300
FUZZY_SUGGESTION_COUNT = 3
FUZZY_MIN_SCORE = 60  # 0-100; below this a "suggestion" is just noise

SYSTEM_PROMPT = """You are the assistant for StartLine, a fantasy football site that blends \
DFS projections, sportsbook betting lines, and expert consensus into one expected-points \
number per player, called the blended score.

You help people make start/sit decisions.

Rules you must follow:
- Never state a projection, score, or probability from memory. Every number you give must \
come from the player data provided to you in this conversation.
- If a player was asked about but has no data provided, say so plainly rather than guessing \
or filling the gap with a number of your own.
- The blended score is the headline number. Higher is better.
- A "high ceiling" flag means the betting markets imply unusual upside. It is context for \
close calls, not part of the blended score.
- An injury code (Q, D, OUT, IR, PUP) is a real availability risk. Mention it whenever a \
player you are recommending carries one.
- When two players are within about 0.5 points, say it is close to a coin flip rather than \
implying false precision. Then point at what actually separates them: the individual \
sources, the ceiling flag, or an injury.
- Be brief. Two or three sentences for a simple comparison. Lead with the recommendation.
- Write plain prose. No markdown, no asterisks for bold, no bullet points, no headings. The \
answer is rendered as plain text, so any markup shows up literally as punctuation.
- Never use an em dash. Use a comma, period, colon, or parentheses instead.
- You only know about the week currently loaded on the site. You have no live news, no \
injury updates beyond the tags in the data, and no knowledge of games that have been played.
"""

RESOLVE_SYSTEM_PROMPT = """You match a fantasy football question to player names from a \
provided list.

Rules:
- Return ONLY names that appear character-for-character in the provided list. Never invent, \
abbreviate, correct, or alter a name — copy it exactly as given.
- Handle nicknames, initials, and casual references (e.g. "CMC" means Christian McCaffrey if \
he's on the list; "Kenneth Walker" means Kenneth Walker III if that's the listed form).
- If you are not confident which listed player a name refers to, leave it out rather than \
guessing.
- If the question mentions what seems like a player name that has no reasonable match on the \
list, put that name (as the user wrote it) in unmatched_mentions instead of names.
- An empty names list is a correct answer when nothing on the list matches.
"""

RESOLVE_TOOL = {
    "name": "resolved_players",
    "description": (
        "Report which players from the provided list the question refers to, plus any "
        "player-like mentions that couldn't be matched to the list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Canonical names, copied exactly from the provided list.",
            },
            "unmatched_mentions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Player-like names mentioned in the question, as typed, that don't match anyone on the list.",
            },
        },
        "required": ["names", "unmatched_mentions"],
    },
}


class ChatNotConfigured(Exception):
    """Raised when no Anthropic API key is available."""


class ChatAuthFailed(Exception):
    """Raised when the key is present but Anthropic rejects it.

    Worth distinguishing from a generic failure: the usual cause is a stray
    space, newline, or quote picked up when pasting the key into a hosting
    provider's environment-variable form, and a generic "unavailable" message
    sends you looking in the wrong place.
    """


def _get_client():
    import anthropic

    # Strip whitespace and stray quotes: the usual mistake when pasting a key
    # into a hosting provider's environment-variable form is a trailing newline
    # or a wrapping quote, both of which Anthropic rejects as an invalid key.
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip().strip('"').strip("'")
    if not api_key:
        raise ChatNotConfigured("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def _resolve_players(
    client, question: str, all_players: list[dict], on_usage: Optional[Callable[[int, int], None]]
) -> tuple[list[str], list[str]]:
    """Stage 1. Returns (canonical_names, unmatched_mentions) as the model
    reported them — neither list is validated against real data yet."""
    import anthropic

    player_list = "\n".join(p["name"] for p in all_players)
    user_msg = f"Question: {question}\n\nPlayer list:\n{player_list}"

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=RESOLVE_MAX_TOKENS,
            system=RESOLVE_SYSTEM_PROMPT,
            tools=[RESOLVE_TOOL],
            tool_choice={"type": "tool", "name": "resolved_players"},
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.AuthenticationError as exc:
        raise ChatAuthFailed(str(exc)) from exc

    if on_usage:
        on_usage(response.usage.input_tokens, response.usage.output_tokens)

    for block in response.content:
        if block.type == "tool_use":
            return block.input.get("names", []), block.input.get("unmatched_mentions", [])
    return [], []


def _validate_names(names: list[str], all_players: list[dict]) -> tuple[list[dict], list[str]]:
    """Stage 2, the guardrail. A name only counts as resolved if it
    exact-matches a real player after normalization — a near-miss or
    hallucinated name is treated as unresolved, never as "close enough"."""
    index = {}
    for p in all_players:
        index.setdefault(normalize_name(p["name"]), p)

    validated, failed = [], []
    for name in names:
        player = index.get(normalize_name(name))
        if player:
            validated.append(player)
        else:
            failed.append(name)
    return validated, failed


def _fuzzy_suggestions(name: str, all_players: list[dict]) -> list[str]:
    """A fallback SUGGESTION mechanism only, shown so a person can pick the
    right player from a clarifying message — never used to silently resolve
    a name on its own."""
    choices = [p["name"] for p in all_players]
    matches = fuzz_process.extract(name, choices, limit=FUZZY_SUGGESTION_COUNT)
    return [name for name, score, _ in matches if score >= FUZZY_MIN_SCORE]


def _clarification_message(unresolved: list[str], all_players: list[dict]) -> str:
    if not unresolved:
        return "I couldn't find a player matching your question in this week's data. Try naming them directly."

    parts = []
    for name in unresolved:
        suggestions = _fuzzy_suggestions(name, all_players)
        if suggestions:
            parts.append(f'"{name}" (did you mean {", ".join(suggestions)}?)')
        else:
            parts.append(f'"{name}"')
    return "I couldn't find " + "; or ".join(parts) + " in this week's data. Try a full name."


def _compose_answer(
    client, question: str, validated_players: list[dict], rows_by_id: dict,
    week: int, scoring_format_label: str, on_usage: Optional[Callable[[int, int], None]],
) -> str:
    """Stage 3. Builds the real-data block from our own stored rows (keyed
    by the validated player's ID, never by name the model gave back) and
    asks the model to answer using only that."""
    import anthropic

    data_lines = []
    for player in validated_players:
        row = rows_by_id.get(player["id"])
        if row is None:
            data_lines.append(f"{player['name']}: no data available for this week.")
            continue
        data_lines.append(
            f"{row['name']} ({row['position']}, {row['team']}): "
            f"blended {row['blended']}, DFS projection {row['dfs_pts']}, "
            f"sportsbook projection {row['betting_pts']}, "
            f"injury {row['injury'] or 'none'}, "
            f"high ceiling {'yes' if row.get('boom_flag') else 'no'}, "
            f"expert perspective {row.get('expert') or 'unavailable'}."
        )

    data_block = "\n".join(data_lines) if data_lines else "No players were resolved for this question."
    system = f"{SYSTEM_PROMPT}\nThe site is currently showing Week {week}, {scoring_format_label}."
    user_msg = f"Question: {question}\n\nPlayer data:\n{data_block}"

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.AuthenticationError as exc:
        raise ChatAuthFailed(str(exc)) from exc

    if on_usage:
        on_usage(response.usage.input_tokens, response.usage.output_tokens)

    if response.stop_reason == "refusal":
        return "I can't help with that one. Try asking about a start/sit decision."

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or "I couldn't find an answer to that. Try naming the players directly."


def answer_question(
    question: str,
    rows: list[dict],
    all_players: list[dict],
    week: int,
    scoring_format_label: str,
    on_usage: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Answer one question. Returns the assistant's text.

    `rows` is this week's real numbers (_player_rows() output) — used to
    pull data once a name is resolved. `all_players` is every active
    skill-position player (id + name), the full candidate list for name
    resolution, independent of who has data this week (a benched or bye-week
    player still needs to be *recognized*, even if we then have to say
    honestly that we have no numbers for them).

    `on_usage(input_tokens, output_tokens)` is called after every API call so
    the caller can enforce a spend cap.
    """
    client = _get_client()

    question = question.strip()[:MAX_QUESTION_CHARS]
    if not question:
        return "Ask me something about this week's players."

    names, unmatched_mentions = _resolve_players(client, question, all_players, on_usage)
    validated, failed_validation = _validate_names(names, all_players)

    unresolved = unmatched_mentions + failed_validation
    if not validated:
        return _clarification_message(unresolved, all_players)

    rows_by_id = {r["id"]: r for r in rows}
    answer = _compose_answer(
        client, question, validated, rows_by_id, week, scoring_format_label, on_usage
    )

    if unresolved:
        clarification = _clarification_message(unresolved, all_players)
        return f"{answer}\n\n{clarification}"
    return answer
