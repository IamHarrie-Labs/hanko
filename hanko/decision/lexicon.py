"""The keyword interpreter, taught to recognise a token by its name.

News channels write "Bitcoin", not "$BTC". The keyword interpreter only sees
cashtags, so on a feed of headlines it reads nothing at all, and every
decision abstains for want of evidence that was sitting right there.

This interpreter finds subjects the way the model interpreter's validator
does: a cashtag, a bare ticker as a whole word, or an unambiguous common
name from ALIASES. Stance, conviction and urgency come from the same word
lists as the keyword interpreter, matched as whole words: the keyword
interpreter's substring match reads "long" inside "along" as bullish, which
on a feed of headlines is the commonest false reading there is. So
"Bitcoin falls below $80k" names BTC and reads neutral: a price move is not
an opinion.

It is pure and free, which is what lets a scheduled sweep run every few
hours with no key and no spend. It has its own interpreter_id, so no
existing keyword decision changes id.
"""

from __future__ import annotations

import re

from .llm_interpreter import ALIASES, names_token
from .reading import KeywordInterpreter


class LexiconInterpreter(KeywordInterpreter):
    interpreter_id = "lexicon"
    interpreter_version = "1.0.0"

    def subjects(self, text: str) -> list[str]:
        found = set(super().subjects(text))
        found.update(ticker for ticker in ALIASES if names_token(text, ticker))
        return sorted(found)

    def score(self, lowered: str, table: dict[str, float]) -> float:
        return sum(
            weight
            for word, weight in table.items()
            if re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", lowered)
        )
