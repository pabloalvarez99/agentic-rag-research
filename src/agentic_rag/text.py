"""Word-level helpers shared by the retrieval fixture and the critic.

Both of them ask the same question of a string — *which words in it carry
meaning?* — and they have to answer it identically. If the fake backend scored a
passage on one tokenisation and the critic measured coverage on another, a run
could retrieve a passage *because* it matched the question and then be told the
question's terms are uncovered. That contradiction would be invisible in the
trace, so the tokeniser lives in one module and both sides import it.

Nothing here is a retrieval technique. It is a lowercase word split with a small
stopword list, chosen so the free path stays deterministic and explainable.
"""

from __future__ import annotations

import re
from typing import Final

_WORD: Final = re.compile(r"[a-z0-9]+")

_STOPWORD_TEXT: Final = (
    "a an the and or but if is are was were be been being do does did of on in to for "
    "from with by at as it its that this these those what which who whom how why when where"
)
"""Words carried by nearly every passage. Left in, they would score noise as overlap."""

STOPWORDS: Final[frozenset[str]] = frozenset(_STOPWORD_TEXT.split())
"""The stopword set applied by :func:`keyword_terms`."""


def keyword_terms(text: str) -> set[str]:
    """Return the scoring terms of a string: lowercased words, stopwords removed.

    Args:
        text: Any string — a question, a sub-question, or a passage.

    Returns:
        The distinct terms worth scoring. Empty when the string carries none,
        which is a meaningful answer: a fragment with no terms is not a
        sub-question worth spending a step on.
    """
    return {word for word in _WORD.findall(text.lower()) if word not in STOPWORDS}
