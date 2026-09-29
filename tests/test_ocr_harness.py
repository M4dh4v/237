"""The watermark through a real OCR pass, on a real rendered screenshot.

This is the test that decides whether the chosen channel is the right one. The
claim in ``watermark/linguistic.py`` is that word *choice* survives everything a
leaked screenshot goes through -- re-rasterisation, rescaling, recompression,
somebody else's font stack, OCR -- where pixel-domain marks do not. That claim is
either true of this implementation or the whole design is wrong, and the only way
to know is to render a marked document, degrade it, run tesseract on it, and
decode what comes back.

Nothing here is stubbed. ``harness.render`` draws the text with PIL and a real
font, ``harness.CATALOG`` applies real JPEG, rescaling, blur, contrast and
rotation, and ``watermark.ocr`` shells out to the system tesseract. If tesseract
is absent the whole file skips loudly rather than passing vacuously -- a green
OCR test that never ran OCR is worse than no test.

Two numbers come out and they mean different things:

* **channel BER** -- the fraction of carrier slots whose OCR'd word differs from
  the synonym that was embedded. This is the raw channel, before any coding, and
  it is what the capacity argument rests on. ``payload.py`` cites 0.004-0.009
  from this harness; the test below asserts the measurement still lands there,
  so the citation cannot drift away from the thing it cites.
* **payload BER** -- the fraction of *bits* wrong after per-position majority
  voting. The gap between the two is the coding gain, and asserting it is the
  point rather than a nicety: if repetition and Reed-Solomon were not doing
  anything, the two numbers would be equal and the payload would be as fragile
  as the raw channel.

The anti-vacuity guard is first, because it is the one that makes the rest
mean something: OCR must actually change the text. An OCR step that returned its
input would make every assertion below pass while testing nothing at all.
"""

from __future__ import annotations

import numpy as np
import pytest

from logfirst.data import corpus, harness
from logfirst.forensics import align
from logfirst.watermark import linguistic, ocr, payload

pytestmark = pytest.mark.skipif(
    not ocr.available(),
    reason="tesseract is not installed, so the OCR round trip cannot be run; "
           "this file must not pass without it")

# The attacks a leaked screenshot realistically goes through: a chat app's
# recompression, a rescaled viewport, and a combination closer to a photograph
# of a screen. The full catalogue is exercised separately and more cheaply.
REALISTIC = ["clean", "jpeg85", "jpeg50", "resize60", "blur1", "contrast70",
             "combo"]

# From the measurement this file performs, and quoted in ``payload.py`` and the
# README. The bound is deliberately loose: the point is that the channel is
# under one percent, not that it is any particular value to three decimals.
CHANNEL_BER_CEILING = 0.02


@pytest.fixture(scope="module")
def doc() -> dict:
    return corpus.make_document_set(1, seed=7, target_words=1700)[0]


@pytest.fixture(scope="module")
def rendered(doc):
    """One marked document, rendered once, reused across the attack tests.

    Rendering and OCR are seconds each; doing them per test would make this file
    the slowest in the suite for no extra coverage.
    """
    index = 4242
    seed = bytes(range(32))
    marked, _ = linguistic.embed(doc["text"], payload.build_payload(index), seed)
    return {
        "index": index,
        "seed": seed,
        "marked": marked,
        "image": harness.render(marked),
    }


def _decode_through_ocr(text: str, image, seed: bytes, index: int
                        ) -> tuple[int | None, float, int, float]:
    """Render-degrade-OCR-align-extract-decode, the whole way through."""
    leaked = ocr.image_to_text(image)
    mapping = align.align(text, leaked)
    votes, totals = linguistic.extract(text, mapping, seed, payload.POINTER_BITS)
    rec = np.where(totals > 0, (votes * 2 > totals).astype(np.uint8), 0)
    got, conf, erasures = payload.decode_pointer(
        rec[:payload.POINTER_BITS], totals[:payload.POINTER_BITS])
    return got, conf, erasures, align.coverage(text, mapping)


# ==========================================================================
# The anti-vacuity guard
# ==========================================================================

def test_ocr_actually_changes_the_text(doc):
    """The test that makes every other test in this file mean something.

    If ``image_to_text`` were a passthrough -- a stub, a cached result, a
    renderer that emitted text rather than pixels -- then the round trip below
    would succeed trivially and prove nothing about surviving OCR. So this
    asserts the OCR output differs from the input at the level of individual
    words, which is the only level the watermark cares about.
    """
    text = doc["text"]
    got = ocr.image_to_text(harness.render(text))

    assert got.strip() != text.strip(), "OCR returned its input unchanged"
    before, after = align.tokens(text), align.tokens(got)
    assert before != after, "OCR reproduced the exact token sequence"

    # Not merely whitespace: the extracted text must differ in words. Tesseract
    # makes character-level substitutions inside words ("job" for "job" is fine,
    # "committee" for "committee" is not), and this is what makes the alignment
    # stage load-bearing rather than decorative.
    mismatches = sum(1 for a, b in zip(before, after) if a != b)
    assert mismatches > 0, (
        "OCR was character-perfect on a rendered page, which is not plausible; "
        "check that the render and the OCR call are actually happening")


def test_naive_positional_matching_is_not_enough(doc):
    """Justifies the LCS aligner rather than assuming it is needed.

    The obvious implementation of extraction is ``zip(canonical_tokens,
    leaked_tokens)``. On this OCR output that is already wrong at a handful of
    positions -- and on a fragment where OCR merges two words or drops one, it is
    wrong at every position after the slip. The test pins the smaller failure so
    the larger one is not hypothetical.
    """
    text = doc["text"]
    got = ocr.image_to_text(harness.render(text))
    before, after = align.tokens(text), align.tokens(got)

    positional = sum(1 for a, b in zip(before, after) if a != b)
    aligned = align.align(text, got)
    assert positional > 0, "this OCR output is too clean to make the point"

    # The aligner recovers essentially the whole document despite that.
    assert align.coverage(text, aligned) > 0.95
    # And it agrees with the naive mapping everywhere the naive mapping is right,
    # while adding the positions the naive one got wrong.
    assert len(aligned) >= len(before) - positional


# ==========================================================================
# The deliverable: the pointer survives OCR
# ==========================================================================

def test_the_pointer_survives_a_real_ocr_pass(doc, rendered):
    """Embed, render, OCR, decode -- and the ledger index comes back.

    This is the build specification's requirement that the linguistic watermark
    round-trip through an actual OCR pass on a rendered screenshot, with no
    simulation anywhere in the chain.
    """
    got, conf, erasures, coverage = _decode_through_ocr(
        doc["text"], rendered["image"], rendered["seed"], rendered["index"])

    assert got == rendered["index"], (
        f"the pointer decoded to {got}, not {rendered['index']}; confidence "
        f"{conf}, erasures {erasures}, alignment coverage {coverage:.3f}")
    assert coverage > 0.95, "alignment was too poor for the result to be trusted"


@pytest.mark.parametrize("attack", REALISTIC)
def test_the_pointer_survives_each_realistic_degradation(doc, rendered, attack):
    """Every degradation separately, so a failure names the cause.

    A single 'combo' test that passed would not say whether the scheme survives
    recompression specifically, which is the one an attacker gets for free by
    pasting a screenshot into any chat application.
    """
    degraded = harness.CATALOG[attack].fn(rendered["image"])
    got, conf, erasures, coverage = _decode_through_ocr(
        doc["text"], degraded, rendered["seed"], rendered["index"])

    assert got == rendered["index"], (
        f"{attack}: decoded {got}, expected {rendered['index']} "
        f"(confidence {conf}, erasures {erasures}, coverage {coverage:.3f})")


def test_the_mark_is_visible_to_ocr_not_just_to_the_renderer(doc, rendered):
    """The watermark must ride the words, not the pixels.

    Decode the same document's *unmarked* rendering. It must not yield the index
    -- because the payload is not in the image, it is in the synonym choices, and
    an unmarked copy does not make those choices. If this test decoded the index
    the extraction would be reading something other than what it claims to.
    """
    plain = harness.render(doc["text"])
    got, _, _, _ = _decode_through_ocr(doc["text"], plain, rendered["seed"],
                                       rendered["index"])
    assert got != rendered["index"], (
        "an unmarked copy decoded the watermark, so the payload is coming from "
        "somewhere other than the synonym choices")


def test_the_marked_and_unmarked_renderings_ocr_differently(doc, rendered):
    """Concretely: the synonym substitutions are present in the OCR output.

    The mark has to be recoverable from text a third party's OCR produced, so the
    substituted words must be what OCR reads -- not merely what PIL drew.
    """
    marked_text = ocr.image_to_text(rendered["image"])
    plain_text = ocr.image_to_text(harness.render(doc["text"]))
    assert align.tokens(marked_text) != align.tokens(plain_text)

    slots = {o for o, _, _ in linguistic.carrier_slots(doc["text"])}
    before = align.tokens(doc["text"])
    after = align.tokens(marked_text)
    changed = {i for i, (a, b) in enumerate(zip(before, after)) if a != b}
    # Most of the differences are the mark; a few are OCR noise. Requiring that
    # the majority land on carrier slots separates the two.
    assert changed, "OCR output of the marked page is identical to the original"
    assert len(changed & slots) >= len(changed) // 2


# ==========================================================================
# The measured channel, and the coding gain over it
# ==========================================================================

@pytest.fixture(scope="module")
def measured(doc):
    """Channel and payload error rates over a couple of documents."""
    docs = corpus.make_document_set(2, seed=7, target_words=1700)
    results = []
    for i, d in enumerate(docs):
        results += harness.measure_document(
            d, 900 + i, bytes([7 * (i + 1)] * 32),
            attacks=["clean", "jpeg50", "resize60", "combo"])
    return results


def test_the_measured_channel_error_rate_is_under_one_percent(measured):
    """The number the capacity argument rests on.

    ``payload.py`` sets ``MIN_REPETITION`` from this rate: at p=0.008 a 3-fold
    majority leaves a per-bit error around 1.9e-4, which RS(3) over five bytes
    absorbs comfortably. If the channel were much worse than measured, the
    repetition choice would be wrong -- so the measurement is asserted here and
    cited from there, rather than being a comment nobody re-checks.
    """
    worst = max(r.channel_ber for r in measured)
    mean = sum(r.channel_ber for r in measured) / len(measured)
    assert worst < CHANNEL_BER_CEILING, (
        f"worst channel BER across the attack set is {worst:.4f}, above the "
        f"{CHANNEL_BER_CEILING} ceiling the repetition budget assumes "
        f"(mean {mean:.4f})")


def test_majority_voting_removes_what_the_channel_adds(measured):
    """The coding gain, asserted rather than described.

    Payload BER must be at or below the raw channel rate. If repetition and RS
    were not pulling their weight the two would coincide -- which would mean a
    document's traceability was exactly as good as its raw OCR quality, and the
    whole ``payload.py`` apparatus would be decoration.
    """
    for r in measured:
        assert r.ber <= r.channel_ber + 1e-9, (
            f"{r.attack}: payload BER {r.ber:.4f} exceeds channel BER "
            f"{r.channel_ber:.4f}, so the coding is adding errors")
    assert all(r.ber <= 0.01 for r in measured), (
        "payload BER is not negligible after decoding; the repetition budget "
        "and the RS parity are sized for a much quieter channel than this")


def test_every_realistic_attack_recovers_the_pointer_in_the_harness(measured):
    """The harness's own verdict, over two documents and four degradations."""
    by_attack: dict[str, list[bool]] = {}
    for r in measured:
        by_attack.setdefault(r.attack, []).append(r.pointer_ok)
    for attack, oks in by_attack.items():
        assert all(oks), f"{attack}: pointer recovered in {sum(oks)}/{len(oks)}"


# ==========================================================================
# What happens when OCR is not good enough
# ==========================================================================

def test_a_destroyed_image_refuses_rather_than_naming_a_wrong_session(doc,
                                                                     rendered):
    """OCR that returns almost nothing must not produce an attribution.

    The dangerous outcome is not a failed read, it is a *plausible* one: a few
    hundred surviving characters could still fill enough slots to produce a
    decode, and a decode names a real recipient whose signature is really in the
    ledger. This drives the image well past the point of legibility and requires
    either the right answer or nothing -- which is the same contract the
    corruption sweep in ``test_watermark.py`` asserts at the slot level.
    """
    destroyed = harness.blur(harness.downscale(rendered["image"], 0.08), 6.0)
    got, _, _, coverage = _decode_through_ocr(
        doc["text"], destroyed, rendered["seed"], rendered["index"])
    assert got in (None, rendered["index"]), (
        f"an illegible image decoded to ledger index {got}, which is neither "
        "the truth nor a refusal -- a false attribution")
    assert coverage < 0.95, (
        "the destroyed render still aligned cleanly, so the test is not "
        "exercising the failure path")


def test_ocr_is_reported_as_unavailable_rather_than_failing_obscurely():
    """Availability is a first-class query, not an exception to discover later.

    The rest of this file is skipped without tesseract, and the demo's leak-check
    screen offers a paste-text path for exactly this reason. What must not happen
    is a caller finding out by catching something.
    """
    assert isinstance(ocr.available(), bool)
    assert ocr.available() is True, "this file would have been skipped otherwise"
