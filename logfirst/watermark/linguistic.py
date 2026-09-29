"""The linguistic watermark: synonym substitution, keystream-masked.

Why this layer is the primary channel
-------------------------------------
The leak-detection front end accepts a screenshot or pasted text, and both
paths destroy the signals that pixel-domain watermarking relies on. A screenshot
is re-rasterised, possibly rescaled, recompressed and re-rendered by someone
else's font stack; character-spacing and line-shift marks do not survive that
plus OCR. Word *choice* does. If the canonical sentence says "the committee
approved the plan" and the leaked copy says "the committee sanctioned the plan",
that difference is still there after OCR, after JPEG, after a phone photo of a
screen. So the linguistic layer carries the payload and the pixel layers, if
present at all, are opportunistic extras.

How a bit is carried
--------------------
256 synonym pairs ("groups"). A *slot* is one occurrence of either word of a
group in the text. At each slot the writer picks which of the two synonyms to
use, and that choice is one bit.

Two things make this a watermark rather than a visible edit:

**The keystream.** The bit actually written at slot ``i`` is
``payload[i % n] XOR keystream[i]``, where the keystream is derived from the
ledger-bound seed. Without the seed an observer sees synonym choices that look
arbitrary -- they cannot read the payload off the page, and cannot tell a marked
copy from a naturally worded one, because the marked bits are pseudorandom.
With the seed, extraction is a XOR away. This is the design the build
specification asks for: choices driven by a keystream derived from the
watermark seed, and the seed is derived from the committed ledger entry, so the
mark and the record are the same event.

**Redundancy.** The payload is tiled across the available slots, so a slot that
OCR mangles costs a vote rather than a bit. Extraction is a per-position
majority vote, which also produces the *soft* information the Reed-Solomon
decoder uses to mark erasures.

What this layer honestly cannot do
----------------------------------
Capacity is set by the document, not by us. A 1000-word document at roughly one
carrier word per 8-12 words yields on the order of 100 slots, and that is the
ceiling on everything downstream -- payload length, Reed-Solomon strength and
Tardos code length all compete for the same slots. A short document is not
weakly marked, it is *unmarked*: below the minimum slot count :func:`embed`
refuses rather than emitting a copy that cannot be traced. See README
"Watermark capacity" for the measured numbers rather than assumed ones.
"""

from __future__ import annotations

import json
import os
import re

import numpy as np

from ..crypto.kdf import watermark_keystream

_LEXICON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "synonym_groups.json")

# A slot needs the word to survive OCR. Short words are where OCR confusions
# cluster ("of"/"or", "is"/"in"), and words with common ligature confusions
# ("rn"->"m", "cl"->"d") are actively dangerous because a misread turns one
# group's word into a *different* group's word -- a silent wrong vote rather
# than a dropped one. The frozen lexicon is already filtered for this; the
# constants are kept here so the filter is visible and testable.
_MIN_LEN = 3

_TOKEN = re.compile(r"[A-Za-z]+")


def load_groups() -> list[list[str]]:
    with open(_LEXICON, "r", encoding="utf-8") as f:
        return json.load(f)["groups"]


GROUPS: list[list[str]] = load_groups()

# word -> (group index, variant bit). Built with setdefault so the first group
# claiming a word wins; the frozen lexicon guarantees no word appears twice, and
# tests/test_watermark.py asserts that rather than trusting it.
_LOOKUP: dict[str, tuple[int, int]] = {}
for _gi, _pair in enumerate(GROUPS):
    for _vi, _w in enumerate(_pair):
        _LOOKUP.setdefault(_w, (_gi, _vi))

N_GROUPS = len(GROUPS)
CARRIER_WORDS = [p[0] for p in GROUPS]


def _match_case(template: str, word: str) -> str:
    """Preserve the original capitalisation when substituting."""
    if template.isupper() and len(template) > 1:
        return word.upper()
    if template[:1].isupper():
        return word.capitalize()
    return word


def carrier_slots(text: str) -> list[tuple[int, int, int]]:
    """Return ``[(token_ordinal, group_index, variant), ...]`` for every slot.

    The token ordinal counts *all* tokens, not just carriers, because the
    extractor needs to line slots up against an aligned leaked text by position.
    """
    out = []
    for ordinal, m in enumerate(_TOKEN.finditer(text)):
        hit = _LOOKUP.get(m.group(0).lower())
        if hit is not None:
            out.append((ordinal, hit[0], hit[1]))
    return out


def slot_count(text: str) -> int:
    return len(carrier_slots(text))


def embed(text: str, payload_bits: np.ndarray, seed: bytes,
          masked_bits: int | None = None) -> tuple[str, int]:
    """Write ``payload_bits`` into ``text``'s carrier slots.

    Returns ``(marked_text, slots_used)``. The payload is tiled across the
    available slots; ``slots_used`` is how many slots the document actually
    offers, which is what the caller reports to the user when it is too few.

    ``masked_bits`` says how many leading payload positions are XORed with the
    keystream. ``None`` masks every position, which is the right behaviour for a
    pointer-only payload. When Tardos positions are present the caller passes
    the pointer length, and here is why that split matters:

    The keystream is bound to one specific ledger entry, so a copy masked
    throughout cannot survive collusion -- two recipients' copies carry two
    different keystreams, and a splice of them is not recoverable by anyone,
    including us. Tardos is precisely the mechanism that has to keep working
    under collusion, so its positions are written **unmasked**. Nothing is lost
    by doing so: a Tardos codeword is already a per-user pseudorandom string, so
    an observer still cannot read it, and being unmasked is what lets a spliced
    mixture remain a linear combination of the colluders' codewords -- which is
    the marking assumption Tardos tracing is proved against.

    The pointer keeps its mask, because its job is different: it names one
    session and must be unreadable without the seed. If a collusion destroys it,
    that is expected, and Tardos is what covers that case.
    """
    payload_bits = np.asarray(payload_bits, dtype=np.uint8).ravel()
    if payload_bits.size == 0:
        raise ValueError("empty payload")
    slots = carrier_slots(text)
    n = len(slots)
    if n == 0:
        return text, 0

    ks = np.unpackbits(np.frombuffer(watermark_keystream(seed, n),
                                     dtype=np.uint8))[:n]
    pos = np.arange(n) % payload_bits.size
    if masked_bits is not None:
        ks = np.where(pos < masked_bits, ks, np.uint8(0))
    # slot index -> bit to write. The XOR against the keystream is what makes
    # the mark unreadable without the seed.
    wanted = np.bitwise_xor(payload_bits[pos], ks)

    state = {"i": 0}

    def repl(m: re.Match) -> str:
        tok = m.group(0)
        hit = _LOOKUP.get(tok.lower())
        if hit is None:
            return tok
        i = state["i"]
        state["i"] += 1
        return _match_case(tok, GROUPS[hit[0]][int(wanted[i])])

    return _TOKEN.sub(repl, text), n


def extract(canonical: str, observed: dict[int, str], seed: bytes,
            nbits: int, masked_bits: int | None = None
            ) -> tuple[np.ndarray, np.ndarray]:
    """Recover soft bits by differencing a leaked text against the canonical.

    ``observed`` maps a *canonical token ordinal* to the word actually found at
    that position in the leaked text (or omits the ordinal if the aligner could
    not place it). Alignment is the caller's job -- see ``forensics/align.py``
    -- because it needs the document to have been identified first.

    ``masked_bits`` must match the value passed to :func:`embed`. Positions
    beyond it are read unmasked, which is what makes the Tardos region
    recoverable from a spliced copy without knowing any participant's seed.

    Returns ``(votes, totals)``, each of length ``nbits``. ``votes[j]`` counts
    how many slots voted for bit 1 at payload position ``j``; ``totals[j]`` is
    how many slots voted at all. Positions with ``totals == 0`` are the
    erasures handed to Reed-Solomon.
    """
    slots = carrier_slots(canonical)
    votes = np.zeros(nbits, dtype=np.int64)
    totals = np.zeros(nbits, dtype=np.int64)
    if not slots:
        return votes, totals

    n = len(slots)
    ks = np.unpackbits(np.frombuffer(watermark_keystream(seed, n),
                                     dtype=np.uint8))[:n]
    if masked_bits is not None:
        pos_all = np.arange(n) % nbits
        ks = np.where(pos_all < masked_bits, ks, np.uint8(0))

    for i, (ordinal, group, _canon_variant) in enumerate(slots):
        word = observed.get(ordinal)
        if word is None:
            continue
        hit = _LOOKUP.get(word.lower())
        if hit is None:
            # The aligner placed a token here but it is not a carrier word at
            # all -- most likely an OCR misread that turned a carrier into
            # something else, or a genuine edit. Count nothing: a wrong vote is
            # worse than a missing one, and Reed-Solomon can use the erasure.
            continue
        observed_group, observed_variant = hit
        if observed_group != group:
            # Right slot, wrong group: the writer's deliberate edit, or a
            # misread that landed on another group's word. Either way the bit
            # is unknown, so it is an abstention, not a 0 or a 1.
            continue
        bit = int(observed_variant) ^ int(ks[i])
        pos = i % nbits
        totals[pos] += 1
        votes[pos] += bit

    return votes, totals
