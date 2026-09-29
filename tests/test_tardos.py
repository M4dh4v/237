"""Tardos fingerprinting: the code, the score, and where accusation stops.

The pointer recovered from a copy names one ledger entry, and a ledger entry is
a session -- which is exactly what a collusion destroys. Two recipients who
compare their copies can splice them, and the result is a paragraph for which no
single session's watermark decodes. Tardos is the layer that survives that, and
it is the reason the system can say anything at all about a spliced leak.

**The property that had to be fixed to make this work.** A document only carries
as many fingerprint positions as it has slots, so the code is regenerated per
document at that length from one stored seed (``data/deploy.py``). That is only
sound if two codes generated at different lengths agree on the positions they
share -- otherwise a recipient's short-document copy and long-document copy carry
unrelated fingerprints and their scores cannot be pooled, which is precisely what
``TardosCode.codeword`` promises and what the generator used to violate. The
first section below is the regression test; it is the reason this file exists in
the shape it does.

**Ranking and accusation are different claims, and the measurements say so.**
``payload.plan``'s docstring asserts that at the code lengths normal documents
support, tracing reliably *ranks* true colluders but does not cross the formal
accusation threshold, and points here for the evidence. The numbers, from the
sweep reproduced as tests below (20 users, two colluders splicing under the
marking assumption, 60 trials per length, seed = trial index):

    m        top-ranked is a colluder   colluder crosses Z   innocent crosses Z
    64              59/60                     0/60                 0/60
    128             60/60                     0/60                 0/60
    256             60/60                     0/60                 0/60
    512             60/60                     0/60                 0/60
    768             60/60                     4/60                 0/60
    full (2987)     60/60                    60/60                 0/60

So a short code is not useless -- it points at the right person almost always --
and it is not proof: at 64 positions it is wrong once in sixty, and nothing
crosses the threshold until the code is thousands of positions long. That is
exactly why the label is "ranking-only" rather than "accusation", and it is why
``MIN_TARDOS`` is a floor rather than a target: at the floor the ranking is good
but not certain, so a candidate list from it is a lead and not a finding. The
distinction is carried into the UI by ``payload.plan``'s ``guarantee`` field and
by ``investigate.py``'s notes, and the tests here are what keep the two from
being conflated.

The one column that is zero everywhere is the one that decides whether the
system is safe to operate: across every code length and both sweeps, no innocent
user ever crossed the threshold.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from logfirst.watermark.payload import MIN_TARDOS
from logfirst.watermark.tardos import TardosCode, code_length

N_USERS = 20
C = 3
EPS = 1e-6


def splice(code: TardosCode, colluders: list[int], rng) -> np.ndarray:
    """A collusion under the marking assumption.

    The colluders can only change a position where their own bits *differ* --
    where they agree, every copy says the same thing and the spliced result must
    too, because the pirate has nothing to choose between. Building the attack
    any other way (flipping bits freely) would be testing a much stronger
    adversary than the code is proved against, and would make the results
    meaningless in the honest direction.
    """
    rows = code.codewords[colluders]
    y = rows[0].copy()
    for j in range(code.m):
        column = rows[:, j]
        if column.min() != column.max():
            y[j] = rng.choice(column)
    return y


def top_is(code: TardosCode, y: np.ndarray, who: list[int]) -> bool:
    return int(np.argmax(code.scores(y))) in who


# ==========================================================================
# Code length
# ==========================================================================

def test_code_length_follows_the_stated_formula():
    """``2 pi^2 c^2 ln(n/eps)`` -- a checkable claim, so it is checked."""
    for n, c, eps in ((10, 3, 1e-6), (100, 2, 1e-3), (7, 4, 1e-8)):
        want = math.ceil(2 * math.pi ** 2 * c * c * math.log(n / eps))
        assert code_length(n, c, eps) == want


def test_code_length_grows_with_users_and_colluders_and_shrinks_with_eps():
    """The directions matter more than the constant.

    More users means more ways to be unlucky; more colluders means a stronger
    attack; a smaller ``eps`` means a tighter false-accusation bound, which is
    bought with more positions. A code length that got one of these backwards
    would still 'work' in the sense of producing scores.
    """
    assert code_length(10, C, EPS) < code_length(100, C, EPS)
    assert code_length(N_USERS, 2, EPS) < code_length(N_USERS, 5, EPS)
    assert code_length(N_USERS, C, 1e-2) < code_length(N_USERS, C, 1e-9)


def test_a_document_cannot_supply_a_formal_guarantee():
    """The honest headline number, asserted so it cannot quietly change.

    A 1700-word document at the corpus's carrier density carries roughly 210
    positions. The formal bound for even a handful of users needs thousands, so
    ``plan`` reports ``ranking-only`` for anything a real document can carry --
    and if a future change made this test fail, the UI's guarantee badge would
    be overstating what the trace proves.
    """
    assert 64 < code_length(N_USERS, C, EPS)
    assert code_length(N_USERS, C, EPS) > 2000


# ==========================================================================
# Generation
# ==========================================================================

def test_the_code_has_the_shape_and_alphabet_the_scoring_expects():
    code = TardosCode.generate(N_USERS, C, EPS, m=500, seed=1)
    assert code.codewords.shape == (N_USERS, 500)
    assert code.codewords.dtype == np.uint8
    assert set(np.unique(code.codewords)) <= {0, 1}
    assert code.p.shape == (500,)
    assert code.n_users == N_USERS and code.m == 500


def test_generation_is_deterministic_in_the_seed():
    """Marker and investigator derive the code separately and must agree.

    The code is never transmitted -- only the seed and the user order are stored
    (``Deployment.tardos_config``). If generation were not a pure function of
    those, the investigator would score against a code nobody was marked with,
    and every score would be noise that still looked like a number.
    """
    a = TardosCode.generate(N_USERS, C, EPS, m=300, seed=99)
    b = TardosCode.generate(N_USERS, C, EPS, m=300, seed=99)
    c = TardosCode.generate(N_USERS, C, EPS, m=300, seed=100)
    assert np.array_equal(a.p, b.p) and np.array_equal(a.codewords, b.codewords)
    assert not np.array_equal(a.codewords, c.codewords)


def test_the_biases_are_arcsine_distributed_with_a_cutoff():
    """The distribution is the security parameter, not a detail.

    Symmetric Tardos draws each position's bias from the arcsine distribution
    truncated at ``t = 1/(10c)``. The truncation is what keeps ``sqrt(p/(1-p))``
    in the score finite: without it, a position with ``p`` near 0 would give
    arbitrary users an unbounded score contribution. The quantiles below are the
    truncated CDF ``(F(p) - F(t)) / (1 - 2F(t))`` inverted.
    """
    c = C
    t = 1.0 / (10 * c)
    F = lambda x: (2 / math.pi) * math.asin(math.sqrt(x))     # noqa: E731
    Ft = F(t)

    code = TardosCode.generate(4, c, EPS, m=100_000, seed=1)
    p = code.p

    # The cutoff is a hard floor and ceiling.
    assert p.min() >= t - 1e-12
    assert p.max() <= 1 - t + 1e-12

    for q in (0.05, 0.2, 0.5, 0.8, 0.95):
        x = math.sin(math.pi / 2 * (Ft + q * (1 - 2 * Ft))) ** 2
        assert abs(float(np.mean(p <= x)) - q) < 0.01, (
            f"the bias distribution is not the truncated arcsine at q={q}")

    # ...and it is emphatically not uniform, which is the point of using it.
    assert float(np.mean(p < 0.25)) > 0.27


def test_the_bits_at_a_position_are_drawn_from_that_positions_bias():
    """``p`` has to describe the matrix, or the score weights are wrong.

    The score is ``sqrt((1-p)/p)`` per agreeing position, so if the matrix did
    not follow ``p`` the weighting would be systematically miscalibrated in a
    way nothing downstream could detect.
    """
    code = TardosCode.generate(400, C, EPS, m=400, seed=5)
    observed = code.codewords.mean(axis=0)
    # 400 users per position: the standard error is at most 0.025.
    assert np.abs(observed - code.p).max() < 0.09
    assert np.abs(observed - code.p).mean() < 0.03


# ==========================================================================
# The prefix property -- the bug this file was written around
# ==========================================================================

def test_a_codeword_is_a_prefix_of_the_full_row():
    """``codeword(i, m)`` truncates; it must not resample."""
    code = TardosCode.generate(N_USERS, C, EPS, m=400, seed=3)
    for i in range(N_USERS):
        assert np.array_equal(code.codeword(i, 40), code.codewords[i][:40])
        assert np.array_equal(code.codeword(i), code.codewords[i])


def test_codes_generated_at_different_lengths_agree_on_the_positions_they_share():
    """The regression test. This used to fail, and the failure was silent.

    The code is regenerated per document from one stored seed, at the length
    that document's slot count allows. A recipient who opened a 1200-word
    document and a 1700-word document therefore holds copies marked from two
    *different* ``TardosCode`` objects. Those objects must agree wherever they
    overlap, or:
      * the two copies carry unrelated fingerprints and their scores cannot be
        pooled across documents (which ``codeword``'s docstring promises), and
      * worse, an investigator scoring a short document's extracted bits against
        a code generated at a longer length is comparing the right user's bits
        to the wrong positions -- producing a confident score for nobody.
    Both draw orders that get this wrong look perfectly reasonable, so it is
    asserted rather than reasoned about.
    """
    short = TardosCode.generate(N_USERS, C, EPS, m=64, seed=7)
    long_ = TardosCode.generate(N_USERS, C, EPS, m=500, seed=7)
    mid = TardosCode.generate(N_USERS, C, EPS, m=200, seed=7)

    assert np.array_equal(short.codewords, long_.codewords[:, :64])
    assert np.array_equal(mid.codewords, long_.codewords[:, :200])
    assert np.array_equal(short.p, long_.p[:64])


def test_the_prefix_property_is_not_vacuous():
    """Guard the guard: the bits must actually depend on the seed and the user.

    A generator that returned all zeros, or the same row for every user, would
    pass the prefix test above trivially and would carry no fingerprint at all.
    """
    a = TardosCode.generate(N_USERS, C, EPS, m=200, seed=7)
    b = TardosCode.generate(N_USERS, C, EPS, m=200, seed=8)
    assert not np.array_equal(a.codewords, b.codewords)
    # Distinct users have distinct rows.
    assert len({a.codewords[i].tobytes() for i in range(N_USERS)}) == N_USERS
    # The alphabet is not collapsed.
    assert 0.3 < a.codewords.mean() < 0.7


# ==========================================================================
# Scoring
# ==========================================================================

def test_a_users_own_codeword_is_its_highest_score():
    """The floor of the whole mechanism: a clean copy fingerpoints its owner."""
    rng = np.random.default_rng(0)
    for trial in range(15):
        code = TardosCode.generate(N_USERS, C, EPS, m=300, seed=trial)
        u = int(rng.integers(N_USERS))
        scores = code.scores(code.codewords[u])
        assert int(np.argmax(scores)) == u


def test_an_innocents_score_is_centred_on_zero():
    """The score is a sum of per-position log-likelihood ratios, so with no
    signal it must not drift positive -- a systematic positive offset would put
    every user near the threshold and make the threshold meaningless."""
    rng = np.random.default_rng(1)
    code = TardosCode.generate(N_USERS, C, EPS, m=2000, seed=2)
    innocent = []
    for _ in range(50):
        y = rng.integers(0, 2, code.m).astype(np.uint8)
        innocent.extend(code.scores(y))
    assert abs(float(np.mean(innocent))) < 0.15 * code.threshold()


def test_the_threshold_is_the_stated_formula():
    code = TardosCode.generate(N_USERS, C, EPS, m=1000, seed=1)
    want = C * math.sqrt(1000 * math.log(N_USERS / EPS))
    assert code.threshold() == pytest.approx(want)


def test_the_threshold_grows_with_the_code_length():
    a = TardosCode.generate(N_USERS, C, EPS, m=100, seed=1)
    b = TardosCode.generate(N_USERS, C, EPS, m=400, seed=1)
    assert b.threshold() > a.threshold()
    # sqrt scaling: four times the positions is twice the threshold.
    assert b.threshold() / a.threshold() == pytest.approx(2.0)


def test_accuse_returns_only_above_threshold_sorted_descending():
    code = TardosCode.generate(N_USERS, C, EPS, m=2000, seed=4)
    hits = code.accuse(code.codewords[3])
    assert hits, "an exact copy must be accused at this length"
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)
    for u, s in hits:
        assert s > code.threshold()
        assert s == pytest.approx(float(code.scores(code.codewords[3])[u]))


def test_rank_always_returns_top_k_even_with_nothing_to_report():
    """The ranking path is what the UI uses when no threshold is crossed."""
    code = TardosCode.generate(N_USERS, C, EPS, m=100, seed=4)
    ranked = code.rank(np.zeros(code.m, dtype=np.uint8), top=5)
    assert len(ranked) == 5
    assert [s for _, s in ranked] == sorted((s for _, s in ranked), reverse=True)


# ==========================================================================
# Ranking versus accusation: the measurements payload.plan points at
# ==========================================================================

TRIALS = 60


def _sweep(m: int) -> dict:
    """Run the collusion experiment at one code length.

    Deterministic: the trial seed is the trial index, so the counts below are
    reproducible rather than flaky.
    """
    rng = np.random.default_rng(2024)
    top_hits = colluder_crossed = innocents_crossed = 0
    max_innocent_ratio = 0.0
    for trial in range(TRIALS):
        code = TardosCode.generate(N_USERS, C, EPS, m=m, seed=trial)
        colluders = [int(x) for x in rng.choice(N_USERS, 2, replace=False)]
        y = splice(code, colluders, rng)

        scores = code.scores(y)
        Z = code.threshold()
        top_hits += int(int(np.argmax(scores)) in colluders)
        colluder_crossed += int(any(scores[u] > Z for u in colluders))
        for u in range(N_USERS):
            if u in colluders:
                continue
            innocents_crossed += int(scores[u] > Z)
            max_innocent_ratio = max(max_innocent_ratio, float(scores[u] / Z))
    return {"top": top_hits, "colluder": colluder_crossed,
            "innocent": innocents_crossed, "max_innocent_ratio": max_innocent_ratio}


@pytest.fixture(scope="module")
def short_sweep() -> dict:
    return _sweep(MIN_TARDOS)


@pytest.fixture(scope="module")
def full_sweep() -> dict:
    return _sweep(code_length(N_USERS, C, EPS))


def test_at_the_minimum_length_a_true_colluder_is_ranked_first(short_sweep):
    """Ranking works far below the formal length -- but not perfectly, and the
    imperfection is the reason ``MIN_TARDOS`` is a floor rather than a target.

    Measured at m=64: 59 of 60 collusions put a true colluder on top. One miss in
    sixty is a good lead and a bad finding, which is precisely the distinction
    the ``ranking-only`` label exists to draw. The assertion is written as a
    bound just under the measurement rather than as equality, because the point
    is the order of magnitude -- if this ever collapsed to chance the floor
    would have stopped meaning anything, and if it ever reached certainty the
    labelling would be understating the trace.
    """
    assert short_sweep["top"] >= TRIALS - 2, (
        f"the top-ranked suspect was a true colluder only "
        f"{short_sweep['top']}/{TRIALS} times at m={MIN_TARDOS}; at this rate "
        "the ranking is not a usable lead")


def test_a_longer_code_ranks_perfectly(full_sweep):
    """At the formal length the ranking is not merely usually right."""
    assert full_sweep["top"] == TRIALS


def test_at_the_minimum_length_nothing_crosses_the_accusation_threshold(short_sweep):
    """No accusation at a short code length -- not even against a real colluder.

    This is the honest half of the same measurement. The score is a real number
    and it is highest for the right person, but it does not clear ``Z``, so
    ``payload.plan`` labels the layout ``ranking-only`` and
    ``investigate.py`` says in as many words that no candidate should be treated
    as a formal accusation. Presenting the top-ranked name without that label is
    the failure this test exists to prevent.
    """
    assert short_sweep["colluder"] == 0, (
        "a short code crossed the accusation threshold; if this becomes true "
        "the 'ranking-only' labelling is understating what the trace proves")
    assert short_sweep["innocent"] == 0
    assert short_sweep["max_innocent_ratio"] < 0.5, (
        "an innocent scored within a factor of two of the accusation threshold "
        "at a length we describe as usable for ranking")


def test_at_the_formal_length_the_accusation_actually_lands(full_sweep):
    """The other direction, so 'ranking-only' is not just a permanent excuse.

    At ``code_length`` the bound applies and a true colluder does cross it. If
    this ever failed, the ``formal`` guarantee would be a promise nothing could
    keep.
    """
    assert full_sweep["colluder"] == TRIALS, (
        f"only {full_sweep['colluder']}/{TRIALS} of the collusions crossed the "
        "threshold at the formal code length")
    assert full_sweep["top"] == TRIALS


def test_no_innocent_is_ever_accused(full_sweep):
    """False accusations are the failure mode that matters.

    An accusation names a person, and a system that accuses an innocent even
    once has done more harm than one that never accuses anybody. Across both
    sweeps the innocent count is zero; this asserts the formal-length one
    separately because it is the configuration where an accusation is actually
    *made* rather than merely ranked.
    """
    assert full_sweep["innocent"] == 0
    assert full_sweep["max_innocent_ratio"] < 0.5


def test_a_collusion_of_three_is_still_traced_at_the_formal_length():
    """The bound is stated for ``c`` colluders; the demo's default is two.

    Three colluders is the harder case the parameter exists for, so it is worth
    knowing the tracing still lands rather than assuming the ``c=3`` in the
    configuration is decorative.
    """
    rng = np.random.default_rng(31)
    m = code_length(N_USERS, C, EPS)
    hits = 0
    for trial in range(12):
        code = TardosCode.generate(N_USERS, C, EPS, m=m, seed=500 + trial)
        colluders = [int(x) for x in rng.choice(N_USERS, 3, replace=False)]
        y = splice(code, colluders, rng)
        scores = code.scores(y)
        Z = code.threshold()
        hits += int(int(np.argmax(scores)) in colluders
                    and any(scores[u] > Z for u in colluders))
        assert not any(scores[u] > Z for u in range(N_USERS)
                       if u not in colluders), "an innocent was accused"
    assert hits >= 10, f"only {hits}/12 three-colluder traces landed"


def test_noise_that_no_colluder_produced_accuses_nobody():
    """A copy that is not any user's codeword must not finger anyone.

    This is the case of an unrelated document, a badly-degraded OCR read, or a
    fragment where extraction recovered noise: the scoring runs anyway, and its
    answer has to be 'nobody', not 'whoever happens to fit'.
    """
    rng = np.random.default_rng(77)
    for m in (MIN_TARDOS, 512):
        for trial in range(30):
            code = TardosCode.generate(N_USERS, C, EPS, m=m, seed=900 + trial)
            y = rng.integers(0, 2, m).astype(np.uint8)
            assert code.accuse(y) == [], (
                f"random bits accused somebody at m={m}, trial {trial}")
