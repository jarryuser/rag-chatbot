"""Bounded conversational context for retrieval without another provider request."""

import re

MAX_HISTORY = 10
MAX_QUERY_CONTEXT = 1600

_REFERENCE = re.compile(
    r"\b(its|their|it|them|this|that|those|these|его|него|её|ее|неё|нее|их|них|"
    r"этого|этому|этом|это|этот|она|оно|он|они|jeho|jej|ich|ňom|neho|tomto|tento)\b",
    re.IGNORECASE,
)
_ELLIPSIS = re.compile(r"^\s*(and\b|what about\b|а\s|и\s|a\s|a čo\b)", re.IGNORECASE)


def needs_context(question: str) -> bool:
    return bool(_REFERENCE.search(question) or _ELLIPSIS.search(question))


def retrieval_query(question: str, history: list[dict] | None = None) -> str:
    """Add recent user turns to referential questions, never assistant assertions.

    This is a search hint, not a semantic rewrite or evidence. Ambiguous references
    can still require clarification, especially after several topic changes.
    """
    if not needs_context(question):
        return question
    prior = []
    remaining = MAX_QUERY_CONTEXT
    for message in reversed((history or [])[-MAX_HISTORY:]):
        if message.get('role') != 'user':
            continue
        content = message.get('content', '').strip()
        if not content:
            continue
        prior.append(content[:remaining])
        remaining -= len(prior[-1])
        if not needs_context(content) or remaining <= 0 or len(prior) == 3:
            break
    if not prior:
        return question
    return '\n'.join([*reversed(prior), question])
