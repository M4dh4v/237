"""Alignment: mapping a leaked fragment onto the canonical document.

Extraction reads the watermark by asking, for each carrier slot in the canonical
text, *what word is at that position in the leaked copy?* So the pipeline needs a
correspondence between canonical token positions and leaked token positions.
Naive positional matching fails immediately on real OCR output, which inserts
and drops tokens freely -- one merged word ("budgetallocation") shifts every
subsequent position by one and the extractor would then be reading a word from
the wrong slot for the rest of the document.

LCS-based alignment via :class:`difflib.SequenceMatcher` handles insertions and
deletions properly. The handling of *replace* blocks is the subtle part and
worth explaining, because getting it wrong silently discards most of the signal:

* An `equal` block maps one-to-one. Easy.
* A `replace` block means the canonical words and the leaked words at that
  region differ. This is usually **not** a deletion -- it is one or two words
  OCR'd wrong (``committee`` -> ``commitee``). If the block has the same length
  on both sides, we map positionally so the extractor can see the (mis)read word
  and decide for itself. It will reject a word that is not a carrier, which is
  the safe direction: a slot that contributes nothing is an erasure, whereas a
  slot mapped to the wrong word is a *wrong vote*.
* Only when the lengths genuinely differ do we treat it as an indel and leave
  the unmatched canonical positions absent from the mapping -- again producing an
  erasure rather than a guess.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_TOKEN = re.compile(r"[A-Za-z]+")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def align(canonical: str, leaked: str) -> dict[int, str]:
    """Return ``{canonical_token_ordinal: leaked_word}``.

    Ordinals absent from the result are positions the aligner could not place;
    the extractor treats those as erasures.
    """
    a = [t.lower() for t in tokens(canonical)]
    b = [t.lower() for t in tokens(leaked)]
    a_raw = tokens(canonical)
    b_raw = tokens(leaked)

    # autojunk off: on short fragments its "popular element" heuristic treats
    # common words as junk and produces a much worse alignment.
    sm = SequenceMatcher(None, a, b, autojunk=False)
    mapping: dict[int, str] = {}

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for off in range(i2 - i1):
                mapping[i1 + off] = b_raw[j1 + off]
        elif tag == "replace":
            span_a, span_b = i2 - i1, j2 - j1
            if span_a == span_b:
                # Same shape: assume misreads, map positionally and let the
                # extractor judge each word.
                for off in range(span_a):
                    mapping[i1 + off] = b_raw[j1 + off]
            else:
                # Genuinely ragged: map the overlapping prefix positionally and
                # leave the rest unmapped (erasures, not guesses).
                for off in range(min(span_a, span_b)):
                    mapping[i1 + off] = b_raw[j1 + off]
        # 'delete' (canonical words with no leaked counterpart) and 'insert'
        # (leaked words with no canonical counterpart) both contribute nothing:
        # the affected canonical positions simply stay unmapped.
    return mapping


def coverage(canonical: str, mapping: dict[int, str]) -> float:
    """Fraction of canonical tokens the aligner managed to place."""
    n = len(tokens(canonical))
    return len(mapping) / n if n else 0.0
