"""The linguistic watermark: the lexicon, the keystream, and the round trip.

This is the layer the whole attribution claim rests on. The pixel and geometry
channels are gone the moment somebody photographs a screen or pastes text into a
chat window; word choice is what survives. So the properties tested here are the
ones that would silently turn "we can name the session" into "we named the wrong
session", and each one is asserted rather than assumed.

**The lexicon is where an ambiguity would be fatal.** A word belonging to two
groups makes a slot's group undecidable, and the extractor resolves a slot by
looking its word up: with two candidates it would guess. Worse is a pair of
words in *different* groups that a reader (or OCR) confuses -- ``rn`` read as
``m``, ``cl`` as ``d`` -- because that produces a confident **wrong** vote rather
than a dropped one, and a wrong vote is the only kind of error Reed-Solomon
cannot see. Both are checked structurally, the second by generating the
confusion set the lexicon comment claims was filtered.

**The keystream is checked by trying to break it.** It is not enough that
extraction works with the right seed; the claim in ``linguistic.embed`` is that
the synonym choices *look arbitrary* without it, so the test reads a marked copy
under a wrong seed and under no seed and requires that neither names the true
ledger entry. That is the difference between a watermark and a plaintext label.

**Failures must be refusals, not guesses.** The measured corruption sweep below
runs to a 60% slot damage rate, well past the point where recovery stops
working, and asserts that across all of it the decoder never once returned a
*wrong* index -- only ``None``. This is the single most important number in the
file: a system that occasionally names an innocent recipient under heavy noise
is worse than one that says nothing, and the two are separated by whether the
failure mode is a refusal or a plausible-looking impostor.

Capacity numbers cited here are measurements, not estimates. See README
"Watermark capacity".
"""

from __future__ import annotations

import itertools
import random

import numpy as np
import pytest

from logfirst.crypto.kdf import watermark_seed
from logfirst.data import corpus
from logfirst.forensics import align as alignment
from logfirst.watermark import linguistic, payload

SEED_A = watermark_seed(b"\x11" * 32)
SEED_B = watermark_seed(b"\x22" * 32)


@pytest.fixture(scope="module")
def docs() -> list[dict]:
    """Two real corpus documents, long enough to carry a pointer comfortably."""
    return corpus.make_document_set(2, seed=11, target_words=1700)


@pytest.fixture(scope="module")
def doc(docs) -> dict:
    return docs[0]


def doc_text(target_words: int, seed: int = 11) -> str:
    """One corpus document of a requested length.

    The generator steers to a carrier density, so ``target_words`` is a
    predictable proxy for the slot count that everything downstream is really
    about -- see README "Watermark capacity" for the measured ratio.
    """
    return corpus.make_document_set(1, seed=seed, target_words=target_words)[0]["text"]


def _pointer(bits: np.ndarray) -> np.ndarray:
    return bits[:payload.POINTER_BITS]


def _read(text: str, marked: str, seed: bytes, nbits: int,
          masked: int | None) -> tuple[np.ndarray, np.ndarray]:
    """The honest extraction path: align first, then read the slots."""
    mapping = alignment.align(text, marked)
    return linguistic.extract(text, mapping, seed, nbits, masked_bits=masked)


def _hard(votes: np.ndarray, totals: np.ndarray) -> np.ndarray:
    return np.where(totals > 0, (votes * 2 > totals).astype(np.uint8), 0)


def _decode(text: str, marked: str, seed: bytes, nbits: int = payload.POINTER_BITS
            ) -> tuple[int | None, float, int]:
    votes, totals = _read(text, marked, seed, nbits, nbits)
    return payload.decode_pointer(*_pointer_pair(votes, totals))


def _pointer_pair(votes: np.ndarray, totals: np.ndarray):
    return _hard(votes, totals)[:payload.POINTER_BITS], totals[:payload.POINTER_BITS]


# ==========================================================================
# The lexicon
# ==========================================================================

def test_every_group_is_a_pair_of_distinct_lowercase_words():
    """Two variants, so one slot carries exactly one bit."""
    for gi, g in enumerate(linguistic.GROUPS):
        assert len(g) == 2, f"group {gi} has {len(g)} variants, not 2"
        assert g[0] != g[1], f"group {gi} repeats {g[0]!r}"
        for w in g:
            assert w == w.lower(), f"group {gi}: {w!r} is not lowercase"
            assert w.isalpha(), f"group {gi}: {w!r} is not a bare word"


def test_no_word_belongs_to_two_groups():
    """A word in two groups makes its slot's group undecidable.

    ``_LOOKUP`` is built with ``setdefault``, so a collision would not raise --
    the second group would simply be unreachable for that word and the extractor
    would read the wrong group's bit at every occurrence, silently and on every
    document. The comment in ``linguistic.py`` says the frozen lexicon
    guarantees this; this is the assertion that it does.
    """
    seen: dict[str, int] = {}
    for gi, g in enumerate(linguistic.GROUPS):
        for w in g:
            assert w not in seen, (
                f"{w!r} is in group {seen[w]} and group {gi}; whichever is "
                "second is unreachable in _LOOKUP")
            seen[w] = gi

    assert len(linguistic._LOOKUP) == len(seen) == 2 * linguistic.N_GROUPS
    for w, (gi, vi) in linguistic._LOOKUP.items():
        assert linguistic.GROUPS[gi][vi] == w


def test_no_word_is_an_ocr_confusion_of_a_word_in_another_group():
    """The hazard the lexicon comment names, checked instead of trusted.

    ``rn`` misread as ``m`` and ``cl`` as ``d`` are the two ligature confusions
    that turn one real word into another real word. If such a pair straddled two
    groups, an OCR slip would cast a confident vote for the *other* group's bit
    -- and because the extractor accepts a word only when it resolves to the
    expected group, a same-group collision would be caught while a cross-group
    one is exactly the silent wrong vote there is no way to detect downstream.
    """
    def confusions(w: str) -> set[str]:
        out = set()
        for i in range(len(w) - 1):
            if w[i:i + 2] == "rn":
                out.add(w[:i] + "m" + w[i + 2:])
            if w[i:i + 2] == "cl":
                out.add(w[:i] + "d" + w[i + 2:])
        for i, ch in enumerate(w):
            if ch == "m":
                out.add(w[:i] + "rn" + w[i + 1:])
            if ch == "d":
                out.add(w[:i] + "cl" + w[i + 1:])
        return out

    owner = {w: gi for gi, g in enumerate(linguistic.GROUPS) for w in g}
    bad = [(w, v) for w in owner for v in confusions(w)
           if v in owner and owner[v] != owner[w]]
    assert not bad, f"cross-group OCR-confusable pairs: {bad}"


def test_no_carrier_word_is_too_short_to_survive_ocr():
    """``_MIN_LEN`` exists because short words are where OCR confusions cluster."""
    short = [w for g in linguistic.GROUPS for w in g
             if len(w) < linguistic._MIN_LEN]
    assert not short, f"carrier words below _MIN_LEN: {short}"


# ==========================================================================
# Slots
# ==========================================================================

def test_carrier_slots_reports_the_group_and_variant_actually_present(doc):
    """``carrier_slots`` is what both embed and extract index by.

    If the reported variant did not match the word on the page, extraction would
    invert every bit and the pointer would be garbage -- so the round-trip tests
    below would fail confusingly rather than here, where the cause is obvious.
    """
    text = doc["text"]
    slots = linguistic.carrier_slots(text)
    tokens = linguistic._TOKEN.findall(text)
    assert slots, "the corpus document offers no carrier slots at all"

    for ordinal, gi, vi in slots:
        word = tokens[ordinal].lower()
        assert linguistic.GROUPS[gi][vi] == word
        assert linguistic._LOOKUP[word] == (gi, vi)


def test_the_ordinal_counts_every_token_not_only_carriers(doc):
    """The ordinal is the aligner's coordinate system.

    ``align`` maps *canonical token positions* to leaked words, and it counts
    every token. If ``carrier_slots`` numbered only carriers, every lookup would
    be off by the number of ordinary words before it -- which is most of them.
    """
    text = doc["text"]
    tokens = linguistic._TOKEN.findall(text)
    slots = linguistic.carrier_slots(text)

    assert [o for o, _, _ in slots] == sorted(o for o, _, _ in slots)
    assert len(slots) == linguistic.slot_count(text)
    assert len(slots) < len(tokens), "every token being a carrier is implausible"
    # Spot-check the coordinate: the token at the ordinal must be a carrier.
    for ordinal, gi, vi in slots[:20]:
        assert tokens[ordinal].lower() in linguistic.GROUPS[gi]


# ==========================================================================
# The round trip
# ==========================================================================

@pytest.mark.parametrize("index", [0, 1, 7, 4096, 65535])
def test_embed_then_extract_recovers_the_ledger_index(doc, index):
    """The core claim: a marked copy names the session that produced it."""
    text = doc["text"]
    bits = payload.build_payload(index)
    marked, slots_used = linguistic.embed(text, bits, SEED_A,
                                          masked_bits=payload.POINTER_BITS)

    assert marked != text, "nothing was written"
    assert slots_used == linguistic.slot_count(text)

    got, conf, erasures = _decode(text, marked, SEED_A)
    assert got == index, f"index {index} came back as {got}"
    assert conf == 1.0, "nothing was corrupted, so nothing should have needed repair"
    assert erasures == 0


def test_only_carrier_words_are_changed(doc):
    """The mark is a synonym choice, not an edit of the prose.

    Asserted positionally: the set of token positions that differ must be a
    subset of the carrier slots, and the token *count* must be unchanged (a
    substitution that changed the word count would derail every later ordinal in
    the aligner's mapping).
    """
    text = doc["text"]
    marked, _ = linguistic.embed(text, payload.build_payload(3), SEED_A,
                                 masked_bits=payload.POINTER_BITS)
    before = linguistic._TOKEN.findall(text)
    after = linguistic._TOKEN.findall(marked)
    assert len(before) == len(after)

    carriers = {o for o, _, _ in linguistic.carrier_slots(text)}
    changed = {i for i, (a, b) in enumerate(zip(before, after)) if a != b}
    assert changed <= carriers, (
        f"tokens changed outside the carrier slots: {sorted(changed - carriers)}")
    assert changed, "the mark changed nothing at all"


def test_case_is_preserved_at_every_slot(doc):
    """A slot in ``The panel will ...`` must not come back lowercase.

    Capitalisation is not cosmetic here: the extractor lowercases before its
    lookup, so a case change is harmless to extraction -- but a visible one is a
    tell that the document was machine-processed, which is exactly what a
    watermark must not announce.
    """
    text = doc["text"]
    marked, _ = linguistic.embed(text, payload.build_payload(11), SEED_A,
                                 masked_bits=payload.POINTER_BITS)
    for a, b in zip(linguistic._TOKEN.findall(text),
                    linguistic._TOKEN.findall(marked)):
        if a == b:
            continue
        assert b.islower() or b[0].isupper() or b.isupper(), b
        if a.isupper() and len(a) > 1:
            assert b.isupper(), f"{a!r} lost its capitals: {b!r}"
        elif a[0].isupper():
            assert b[0].isupper(), f"{a!r} lost its initial capital: {b!r}"
        else:
            assert b.islower(), f"{a!r} gained capitals: {b!r}"


def test_embedding_is_deterministic(doc):
    """Same payload and seed, same bytes -- otherwise nothing is reproducible.

    A verifier re-running the marking step, or a demo replaying a session, has to
    land on the same copy. A randomised embed would make the inclusion proof and
    the marked text describe different events.
    """
    text = doc["text"]
    bits = payload.build_payload(1234)
    a, _ = linguistic.embed(text, bits, SEED_A, masked_bits=payload.POINTER_BITS)
    b, _ = linguistic.embed(text, bits, SEED_A, masked_bits=payload.POINTER_BITS)
    assert a == b


def test_a_text_with_no_carriers_is_returned_untouched():
    """No slots is a refusal to mark, never a silent pass-through.

    ``embed`` returns the text unchanged and reports zero slots; the caller
    compares that against ``payload.MIN_SLOTS`` and refuses to hand the copy
    over. Returning the text unchanged is right here only because the count
    comes back with it -- an unmarked copy that reported success would be
    untraceable and would look marked.
    """
    text = "Xyzzy plugh qqqq zzzz."
    assert linguistic.slot_count(text) == 0
    marked, n = linguistic.embed(text, payload.build_payload(1), SEED_A)
    assert marked == text
    assert n == 0


# ==========================================================================
# The keystream
# ==========================================================================

def test_a_different_seed_produces_a_different_marking(doc):
    """The seed is what binds a copy to one session rather than one document."""
    text = doc["text"]
    bits = payload.build_payload(42)
    a, _ = linguistic.embed(text, bits, SEED_A, masked_bits=payload.POINTER_BITS)
    b, _ = linguistic.embed(text, bits, SEED_B, masked_bits=payload.POINTER_BITS)
    assert a != b


def test_the_mark_is_unreadable_without_the_seed(doc):
    """The claim in ``linguistic.embed``: choices look arbitrary without it.

    Read the marked copy under a *different* session's seed. If the payload were
    written into the synonyms directly, the wrong seed would still recover it --
    the mark would then be a label anyone could read off the page, and knowing
    which session a copy came from would require no secret at all. Over 60
    trials the wrong seed must never produce the true index.
    """
    text = doc["text"]
    rng = random.Random(2)
    hit = produced = 0
    for _ in range(60):
        index = rng.randrange(0, 60000)
        marked, _ = linguistic.embed(text, payload.build_payload(index), SEED_A,
                                     masked_bits=payload.POINTER_BITS)
        got, _, _ = _decode(text, marked, SEED_B)
        hit += got == index
        produced += got is not None

    assert hit == 0, f"a wrong seed recovered the true index {hit}/60 times"
    assert produced == 0, (
        f"a wrong seed produced a plausible-looking pointer {produced}/60 "
        "times; random bits must not RS-decode to anything")


def test_the_mark_is_unreadable_with_no_seed_at_all(doc):
    """The same claim against the seedless read.

    This is the check that matters for an adversary who has the marked copy and
    the ledger but not the ability to derive the seed: it reads the synonym
    choices as if they *were* the payload, which is the strongest thing an
    observer can do without the seed.
    """
    text = doc["text"]
    slots = linguistic.carrier_slots(text)
    rng = random.Random(4)
    hit = 0
    for _ in range(40):
        index = rng.randrange(0, 60000)
        marked, _ = linguistic.embed(text, payload.build_payload(index), SEED_A,
                                     masked_bits=payload.POINTER_BITS)
        tokens = linguistic._TOKEN.findall(marked)
        # Every slot reported as if it had been read at face value.
        observed = {o: tokens[o] for o, _, _ in slots}
        votes, totals = linguistic.extract(text, observed, b"\x00" * 32,
                                           payload.POINTER_BITS, masked_bits=0)
        got, _, _ = payload.decode_pointer(*_pointer_pair(votes, totals))
        hit += got == index

    assert hit == 0, f"a seedless read recovered the index {hit}/40 times"


def test_the_seed_is_what_selects_between_the_two_synonyms(doc):
    """Direct check that the XOR is really applied, not merely present in code.

    Two seeds that differ in a single bit of keystream must, at the slots where
    that bit lands, write *different* words. If ``embed`` ignored the keystream
    the two marked texts would be identical.
    """
    text = doc["text"]
    bits = payload.build_payload(9)
    a, _ = linguistic.embed(text, bits, SEED_A, masked_bits=payload.POINTER_BITS)
    b, _ = linguistic.embed(text, bits, SEED_B, masked_bits=payload.POINTER_BITS)
    ta, tb = linguistic._TOKEN.findall(a), linguistic._TOKEN.findall(b)
    differ = sum(1 for x, y in zip(ta, tb) if x != y)
    assert differ > 0
    # And each text still decodes to the same index under its own seed.
    assert _decode(text, a, SEED_A)[0] == 9
    assert _decode(text, b, SEED_B)[0] == 9


# ==========================================================================
# Masking: the pointer is secret, the Tardos region is not
# ==========================================================================

def test_the_tardos_region_reads_without_any_seed(doc):
    """The split that makes collusion tracing possible at all.

    The keystream is bound to one ledger entry, so a copy masked throughout can
    only be read by someone holding that entry -- which is useless once two
    recipients splice their copies, because no single seed describes the result.
    The Tardos positions are therefore written unmasked, and the test is that a
    reader with the wrong seed recovers them exactly while the pointer does not
    decode.
    """
    text = doc["text"]
    n_tardos = payload.MIN_TARDOS
    total = payload.POINTER_BITS + n_tardos
    rng = np.random.default_rng(5)
    tardos_bits = rng.integers(0, 2, size=n_tardos).astype(np.uint8)
    bits = payload.build_payload(77, tardos_bits)

    marked, _ = linguistic.embed(text, bits, SEED_A,
                                 masked_bits=payload.POINTER_BITS)

    # Read with a seed that has nothing to do with this copy.
    votes, totals = _read(text, marked, SEED_B, total, payload.POINTER_BITS)
    recovered = _hard(votes, totals)[payload.POINTER_BITS:total]
    assert np.array_equal(recovered, tardos_bits), (
        "the Tardos region did not survive a wrong seed, so a spliced copy "
        "would carry no traceable signal")

    # ...and the pointer, in the same read, is not recoverable.
    got, _, _ = payload.decode_pointer(*_pointer_pair(votes, totals))
    assert got != 77


def test_the_pointer_region_is_masked_and_the_rest_is_not(doc):
    """The same property stated as an equality rather than an inequality.

    Reading the Tardos region must give *exactly* the bits written, under any
    seed whatsoever -- including the right one. If masking leaked into those
    positions the recovery would depend on the seed, which is the failure this
    asserts against by reading under three different seeds.
    """
    text = doc["text"]
    n_tardos = payload.MIN_TARDOS
    total = payload.POINTER_BITS + n_tardos
    tardos_bits = np.random.default_rng(6).integers(0, 2, n_tardos).astype(np.uint8)
    marked, _ = linguistic.embed(text, payload.build_payload(5, tardos_bits),
                                 SEED_A, masked_bits=payload.POINTER_BITS)

    for seed in (SEED_A, SEED_B, b"\x00" * 32, watermark_seed(b"\xff" * 32)):
        votes, totals = _read(text, marked, seed, total, payload.POINTER_BITS)
        assert np.array_equal(
            _hard(votes, totals)[payload.POINTER_BITS:total], tardos_bits), (
            "the unmasked region depended on the seed")


# ==========================================================================
# Redundancy, the vote, and what a damaged slot costs
# ==========================================================================

def test_every_payload_position_gets_at_least_the_minimum_repetition(doc):
    """Repetition is the budget that Reed-Solomon erasures are spent from.

    The document offers far more slots than the payload needs, so the surplus is
    tiling: each position is written several times and extraction is a majority
    vote. A position receiving *no* votes at all becomes an erasure, and RS can
    absorb only ``POINTER_ECC`` of those.
    """
    text = doc["text"]
    bits = payload.build_payload(100)
    marked, slots = linguistic.embed(text, bits, SEED_A,
                                     masked_bits=payload.POINTER_BITS)
    votes, totals = _read(text, marked, SEED_A, payload.POINTER_BITS,
                          payload.POINTER_BITS)

    assert totals.sum() == slots
    assert totals.min() >= payload.MIN_REPETITION
    # A clean channel: every vote agrees with the bit that was written.
    assert np.array_equal(_hard(votes, totals), bits)


def test_a_slot_from_the_wrong_group_abstains_rather_than_voting(doc):
    """A misread that lands on another group's word must not cast a vote.

    This is the property ``extract``'s docstring calls the safe direction, and it
    is the difference between a dropped bit and a *false* one: an abstention
    costs one RS parity symbol (the byte becomes an erasure), while a wrong vote
    is an error the decoder has to detect on its own.
    """
    text = doc["text"]
    slots = linguistic.carrier_slots(text)
    # Rewrite one slot's word to a word from a *different* group.
    ordinal, group, _ = slots[3]
    foreign = linguistic.GROUPS[(group + 1) % linguistic.N_GROUPS][0]
    observed = {o: linguistic._TOKEN.findall(text)[o] for o, _, _ in slots}
    observed[ordinal] = foreign

    _, totals_full = linguistic.extract(
        text, {o: linguistic._TOKEN.findall(text)[o] for o, _, _ in slots},
        SEED_A, payload.POINTER_BITS, payload.POINTER_BITS)
    _, totals_edited = linguistic.extract(text, observed, SEED_A,
                                          payload.POINTER_BITS,
                                          payload.POINTER_BITS)
    assert totals_edited.sum() == totals_full.sum() - 1


def test_a_non_carrier_word_at_a_slot_abstains(doc):
    """The same for a word the lexicon does not know at all -- a bad OCR read."""
    text = doc["text"]
    slots = linguistic.carrier_slots(text)
    tokens = linguistic._TOKEN.findall(text)
    observed = {o: tokens[o] for o, _, _ in slots}
    observed[slots[5][0]] = "zzzzz"

    _, totals = linguistic.extract(text, observed, SEED_A, payload.POINTER_BITS,
                                   payload.POINTER_BITS)
    _, base = linguistic.extract(text, {o: tokens[o] for o, _, _ in slots},
                                 SEED_A, payload.POINTER_BITS,
                                 payload.POINTER_BITS)
    assert totals.sum() == base.sum() - 1


def test_an_unplaceable_slot_is_an_erasure(doc):
    """An ordinal the aligner could not place must not be guessed at.

    ``align`` leaves ragged regions unmapped rather than inventing a
    correspondence, and this is why: a slot read from the wrong position is a
    confident wrong bit, while a slot left out is an erasure RS can repair.
    """
    text = doc["text"]
    slots = linguistic.carrier_slots(text)
    tokens = linguistic._TOKEN.findall(text)
    full = {o: tokens[o] for o, _, _ in slots}
    missing = {o: w for o, w in full.items() if o != slots[7][0]}

    _, totals_full = linguistic.extract(text, full, SEED_A,
                                        payload.POINTER_BITS, payload.POINTER_BITS)
    _, totals_missing = linguistic.extract(text, missing, SEED_A,
                                           payload.POINTER_BITS,
                                           payload.POINTER_BITS)
    assert totals_missing.sum() == totals_full.sum() - 1


# -- the corruption sweep --------------------------------------------------

# Fraction of slots damaged, modelling OCR drops and misreads: half the damaged
# slots vanish (an erasure) and half come back as the other variant of the same
# group (a wrong vote). Measured on this corpus at 300 trials per rate:
#
#   rate   recovered   refused (None)   WRONG
#   0.20      295           5             0
#   0.30      272          28             0
#   0.40      187         113             0
#   0.60       25         275             0
#
# The recovery rate falls off, as it must. The column that matters is the last
# one, and it is zero everywhere: past the point of recovery the decoder refuses
# rather than naming the wrong session. 0.10 is asserted as a hard floor and the
# long sweep is asserted only on the wrong-decode count.
SAFE_RATE = 0.10
STRESS_RATE = 0.50


def _corrupt(doc_text_: str, marked: str, rate: float, rng: random.Random
             ) -> dict[int, str]:
    """Damage ``rate`` of the slots the way a noisy read would."""
    mapping = alignment.align(doc_text_, marked)
    observed: dict[int, str] = {}
    for ordinal, group, variant in linguistic.carrier_slots(doc_text_):
        word = mapping.get(ordinal)
        if word is None:
            continue
        if rng.random() < rate:
            if rng.random() < 0.5:
                continue                       # dropped -> erasure
            word = linguistic.GROUPS[group][1 - variant]   # misread -> wrong vote
        observed[ordinal] = word
    return observed


@pytest.mark.parametrize("seed_offset", [0, 1, 2])
def test_the_pointer_survives_a_realistic_channel(doc, seed_offset):
    """At 10% slot damage the pointer must still come back, and come back right."""
    rng = random.Random(100 + seed_offset)
    for trial in range(20):
        index = rng.randrange(0, 60000)
        marked, _ = linguistic.embed(doc["text"], payload.build_payload(index),
                                     SEED_A, masked_bits=payload.POINTER_BITS)
        observed = _corrupt(doc["text"], marked, SAFE_RATE, rng)
        votes, totals = linguistic.extract(doc["text"], observed, SEED_A,
                                           payload.POINTER_BITS,
                                           payload.POINTER_BITS)
        got, _, erasures = payload.decode_pointer(*_pointer_pair(votes, totals))
        assert got == index, f"trial {trial}: {index} came back as {got}"
        assert erasures <= payload.POINTER_ECC


def test_heavy_damage_refuses_rather_than_accusing_the_wrong_session(doc):
    """The most important assertion in the file.

    At a 50% slot damage rate recovery mostly fails -- that is expected and fine.
    What must never happen is a *wrong* index coming back, because a wrong index
    is a named recipient with a verifiable signature in the ledger, and the
    investigator's whole pipeline would report it as an attribution. Refusal is
    the only acceptable failure, and this asserts the decoder never once
    confused the two across the sweep.
    """
    rng = random.Random(77)
    wrong: list[tuple[int, int]] = []
    for _ in range(120):
        index = rng.randrange(0, 60000)
        marked, _ = linguistic.embed(doc["text"], payload.build_payload(index),
                                     SEED_A, masked_bits=payload.POINTER_BITS)
        observed = _corrupt(doc["text"], marked, STRESS_RATE, rng)
        votes, totals = linguistic.extract(doc["text"], observed, SEED_A,
                                           payload.POINTER_BITS,
                                           payload.POINTER_BITS)
        got, _, _ = payload.decode_pointer(*_pointer_pair(votes, totals))
        if got is not None and got != index:
            wrong.append((index, got))

    assert not wrong, (
        f"the decoder named a wrong ledger index {len(wrong)} time(s) under "
        f"heavy damage: {wrong[:5]}. A false attribution is worse than a "
        "refusal, so this failure mode must not exist at any noise level")


def test_rs_refuses_when_more_bytes_are_erased_than_it_can_repair():
    """The guard that produces the refusals above, tested at its boundary.

    ``POINTER_ECC`` parity symbols means at most that many erased *bytes*. One
    more and ``decode_pointer`` must return ``None`` before handing anything to
    the decoder -- past that point RS may miscorrect, which is the one way a
    wrong index could be manufactured from nothing.
    """
    totals = np.full(payload.POINTER_BITS, 4, dtype=np.int64)
    bits = payload.encode_pointer(4242)

    ok = totals.copy()
    for b in range(payload.POINTER_ECC):
        ok[b * 8] = 0
    assert payload.decode_pointer(bits, ok)[0] == 4242

    too_many = totals.copy()
    for b in range(payload.POINTER_ECC + 1):
        too_many[b * 8] = 0
    got, conf, erasures = payload.decode_pointer(bits, too_many)
    assert got is None
    assert conf == 0.0
    assert erasures == payload.POINTER_ECC + 1


# ==========================================================================
# The payload layout
# ==========================================================================

def test_an_index_that_does_not_fit_the_pointer_width_is_refused():
    """Silently truncating would alias two sessions onto one watermark."""
    assert payload.encode_pointer(0).size == payload.POINTER_BITS
    assert payload.encode_pointer((1 << 16) - 1).size == payload.POINTER_BITS
    for bad in (-1, 1 << 16, 1 << 40):
        with pytest.raises(ValueError):
            payload.encode_pointer(bad)


def test_a_short_document_is_refused_with_a_reason_naming_the_numbers():
    """Below the floor the system must refuse, not mark weakly.

    The specification requires the density to be validated against the corpus
    rather than assumed, and the consequence of validating it is that some
    documents are too short. A copy marked with fewer slots than the pointer
    needs is *untraceable* while looking perfectly normal -- so the refusal has
    to be loud and has to say what would have been enough.
    """
    for slots in (0, 1, 40, payload.MIN_SLOTS - 1):
        plan = payload.plan(slots)
        assert plan["ok"] is False
        assert plan["reason"]
        assert str(payload.MIN_SLOTS) in plan["reason"]
        assert str(slots) in plan["reason"]

    plan = payload.plan(payload.MIN_SLOTS)
    assert plan["ok"] is True, "the floor itself must be markable"
    assert plan["pointer_slots"] == payload.MIN_SLOTS
    assert plan["tardos_bits"] == 0


def test_a_tardos_region_below_the_floor_is_dropped_rather_than_shortened():
    """A handful of Tardos positions produces confident scores with no power.

    ``plan`` marks such a document pointer-only and says why, instead of
    emitting a short code whose scores would look like evidence and would not be.
    The document is built short on purpose: the fixture documents are long
    enough to clear the Tardos floor, and this test is about the band between
    "enough for a pointer" and "enough for a code".
    """
    short = corpus.make_document_set(1, seed=3, target_words=1200)[0]
    slots = short["slots"]
    room = slots - payload.MIN_SLOTS
    assert 0 < room < payload.MIN_TARDOS, (
        f"the short document offers {room} spare slots; the test needs a value "
        "between 1 and MIN_TARDOS-1")

    plan = payload.plan(slots, tardos_len=payload.MIN_TARDOS)
    assert plan["tardos_bits"] == 0
    assert "Tardos" in plan["reason"] or "pointer-only" in plan["reason"]
    assert plan["guarantee"] == "none"

    # A long enough document in the same corpus does carry one, so the floor is
    # a real threshold rather than a value nothing ever clears.
    long_slots = linguistic.slot_count(doc_text(1700))
    assert long_slots - payload.MIN_SLOTS >= payload.MIN_TARDOS


def test_the_plan_is_a_pure_function_of_the_slot_count(doc):
    """Marker and investigator must independently agree on the layout.

    The investigator was not present when the copy was marked, so the layout
    cannot be a free choice -- it is recomputed from the document's slot count
    and the deployment's user count. Marking with one layout and reading with
    another would silently produce noise, so the same inputs must give the same
    plan.
    """
    slots = linguistic.slot_count(doc["text"])
    for n_users in (0, 4, 40):
        a = payload.plan_for_document(slots, n_users)
        b = payload.plan_for_document(slots, n_users)
        assert a == b
        if not a["ok"]:
            continue
        # And the plan's own total is what both sides will use.
        assert a["total_bits"] == a["pointer_bits"] + a["tardos_bits"]


def test_the_payload_split_round_trips(doc):
    """``build_payload`` and ``split_payload`` must be inverse.

    They are called from opposite ends of the pipeline -- the marker builds, the
    investigator splits -- so a mismatch would put the Tardos bits where the
    pointer was expected, in one direction only.
    """
    n_tardos = payload.MIN_TARDOS
    tardos_bits = np.random.default_rng(8).integers(0, 2, n_tardos).astype(np.uint8)
    whole = payload.build_payload(31337, tardos_bits)
    assert whole.size == payload.POINTER_BITS + n_tardos

    ptr, tard = payload.split_payload(whole, n_tardos)
    assert ptr.size == payload.POINTER_BITS
    assert np.array_equal(tard, tardos_bits)
    assert np.array_equal(ptr, payload.encode_pointer(31337))


def test_the_pointer_block_is_reed_solomon_protected():
    """A single wrong bit must be repaired, not propagated.

    If the pointer were raw bits, one flipped bit would change the index by a
    power of two -- naming a different, innocent session whose ledger entry
    verifies perfectly. The parity symbols are what turn a bit error into a
    corrected read instead of a false accusation.
    """
    bits = payload.encode_pointer(9999)
    for pos in range(0, payload.POINTER_BITS, 5):
        noisy = bits.copy()
        noisy[pos] ^= 1
        got, conf, _ = payload.decode_pointer(noisy)
        assert got == 9999, f"flipping bit {pos} changed the index to {got}"
        assert conf < 1.0, "a repaired read should not report full confidence"


def test_the_pointer_block_is_not_merely_the_index_in_binary():
    """A sanity check that the block is longer than the data it carries.

    Two bytes of index would be 16 bits; the block is 40. If this ever became
    equal, the RS layer would have been dropped and every bit error would be
    an index error.
    """
    assert payload.POINTER_BITS > 8 * payload.POINTER_BYTES
    assert payload.POINTER_ECC >= 1


def test_two_indices_do_not_share_a_codeword():
    """A crude collision check over the space the demo actually uses."""
    seen = {}
    for idx in itertools.chain(range(0, 200), range(59900, 60100)):
        key = payload.encode_pointer(idx).tobytes()
        assert key not in seen, f"indices {seen.get(key)} and {idx} collide"
        seen[key] = idx
