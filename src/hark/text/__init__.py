"""Rule-based transcript processing: filler cleanup, voice commands, vocabulary."""

EDGE = ".,!?;:…\"“”"
SENTENCE_END = (".", "!", "?", "…")


def norm(token: str) -> str:
    """Lowercased token without edge punctuation, for matching spoken words."""
    return token.strip(EDGE).lower()


def trailing(token: str) -> str:
    """The token's trailing punctuation, e.g. ',' for 'um,'."""
    return token[len(token.rstrip(EDGE)):]


def capitalize(token: str) -> str:
    return token[:1].upper() + token[1:]
