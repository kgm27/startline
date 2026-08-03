"""Natural-language question answering over the site's own player data.

The whole point of StartLine is that every number traces back to a real market,
so the assistant is never allowed to recall a number from training. It gets one
tool, `lookup_players`, which reads the same `_player_rows()` output the
Dashboard and Compare pages render, and it answers only from what that returns.

Cost control is a first-class concern here: this is a public endpoint that
spends real money, so the loop is capped at a small number of tool round trips
and the caller is expected to enforce a per-IP rate limit and a daily budget.
"""
from __future__ import annotations  # this project runs Python 3.9; `X | None` needs 3.10

import json
import logging
import os
from typing import Callable, Optional

MODEL = "claude-haiku-4-5"

# A question needs at most one lookup, then an answer. Three iterations leaves
# room for a follow-up lookup (e.g. "and how does he compare to the top RB?")
# without letting a confused loop run up a bill.
MAX_TOOL_ROUNDS = 3
MAX_TOKENS = 1024
MAX_QUESTION_CHARS = 500

SYSTEM_PROMPT = """You are the assistant for StartLine, a fantasy football site that blends \
DFS projections, sportsbook betting lines, and expert consensus into one expected-points \
number per player, called the blended score.

You help people make start/sit decisions.

Rules you must follow:
- Never state a projection, score, or probability from memory. Every number you give must \
come from the lookup_players tool in this conversation.
- If a player is not in the data, say so plainly. Do not guess or substitute a similar name.
- The blended score is the headline number. Higher is better.
- A "high ceiling" flag means the betting markets imply unusual upside. It is context for \
close calls, not part of the blended score.
- An injury code (Q, D, OUT, IR, PUP) is a real availability risk. Mention it whenever a \
player you are recommending carries one.
- When two players are within about 0.5 points, say it is close to a coin flip rather than \
implying false precision. Then point at what actually separates them: the individual \
sources, the ceiling flag, or an injury.
- Be brief. Two or three sentences for a simple comparison. Lead with the recommendation.
- You only know about the week currently loaded on the site. You have no live news, no \
injury updates beyond the tags in the data, and no knowledge of games that have been played.
"""

TOOLS = [
    {
        "name": "lookup_players",
        "description": (
            "Look up StartLine's real data for one or more players by name. "
            "Call this before answering any question that involves specific players. "
            "Returns the blended score, DFS projection, sportsbook projection, position, "
            "team, injury designation, and high-ceiling flag for each player found, plus "
            "a list of any names that could not be matched."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Player names as the user wrote them, e.g. ['Joe Burrow', 'Dak']",
                }
            },
            "required": ["names"],
        },
    }
]


class ChatNotConfigured(Exception):
    """Raised when no Anthropic API key is available."""


def _match(rows: list[dict], query: str) -> dict | None:
    """Find a player by a loosely-typed name.

    People write "Dak", "burrow", "CMC". Exact match first, then a
    case-insensitive substring on the full name, then on the surname alone.
    """
    q = query.strip().lower()
    if not q:
        return None
    for r in rows:
        if r["name"].lower() == q:
            return r
    for r in rows:
        if q in r["name"].lower():
            return r
    for r in rows:
        surname = r["name"].split()[-1].lower()
        if surname == q:
            return r
    return None


def lookup_players(rows: list[dict], names: list[str]) -> dict:
    """The tool body. Reads only from `rows`, which is _player_rows() output."""
    found, missing = [], []
    for name in names[:8]:  # a question about more than 8 players is not a real question
        row = _match(rows, name)
        if row is None:
            missing.append(name)
            continue
        found.append({
            "name": row["name"],
            "position": row["position"],
            "team": row["team"],
            "blended": row["blended"],
            "dfs_projection": row["dfs_pts"],
            "sportsbook_projection": row["betting_pts"],
            "injury": row["injury"],
            "high_ceiling": bool(row.get("boom_flag")),
            "expert": row.get("expert"),
        })
    return {"players": found, "not_found": missing}


def answer_question(
    question: str,
    rows: list[dict],
    week: int,
    scoring_format_label: str,
    on_usage: Callable[[int, int], None] | None = None,
) -> str:
    """Answer one question. Returns the assistant's text.

    `on_usage(input_tokens, output_tokens)` is called after every API call so the
    caller can enforce a spend cap.
    """
    import anthropic

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise ChatNotConfigured("ANTHROPIC_API_KEY is not set")

    question = question.strip()[:MAX_QUESTION_CHARS]
    if not question:
        return "Ask me something about this week's players."

    client = anthropic.Anthropic()
    system = f"{SYSTEM_PROMPT}\nThe site is currently showing Week {week}, {scoring_format_label}."
    messages = [{"role": "user", "content": question}]

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            messages=messages,
        )
        if on_usage:
            on_usage(response.usage.input_tokens, response.usage.output_tokens)

        if response.stop_reason == "refusal":
            return "I can't help with that one. Try asking about a start/sit decision."

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return text or "I couldn't find an answer to that. Try naming the players directly."

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                data = lookup_players(rows, block.input.get("names", []))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(data),
                })
            except Exception:
                logging.exception("lookup_players failed")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "Lookup failed.",
                    "is_error": True,
                })
        messages.append({"role": "user", "content": results})

    return "That took more steps than expected. Try asking about specific players by name."
