"""Symmetric Tardos collusion-resistant fingerprinting codes (Škorić et al.).

The problem this solves: if 2-3 recipients compare their individually-marked
copies and average/splice them to erase the mark (or to frame an innocent user),
a naive per-copy id is destroyed. A Tardos code assigns each user a long random
binary codeword drawn from position-dependent biases; even after the colluders
mix their copies under the *marking assumption* (they can only alter positions
where their bits differ), an accusation score still fingers at least one true
colluder with provably bounded false-positive probability.

Reference: G. Tardos, "Optimal probabilistic fingerprint codes" (2003/2008);
B. Škorić et al., "Symmetric Tardos fingerprinting codes" (2008) — the symmetric
score variant implemented here.
"""
from __future__ import annotations

import math

import numpy as np


def code_length(n_users: int, c: int, eps: float) -> int:
    """A practical symmetric-Tardos length. The asymptotic optimum is
    m ~ 2 c^2 ln(n/eps) (pi^2 constant folded in); we use a safe constant."""
    return int(math.ceil(2 * math.pi ** 2 * c * c * math.log(n_users / eps)))


class TardosCode:
    """A generated code: per-position biases ``p`` and the ``n x m`` bit matrix."""

    def __init__(self, codewords: np.ndarray, p: np.ndarray, c: int, eps: float):
        self.codewords = codewords          # shape (n_users, m) uint8
        self.p = p                          # shape (m,) float bias per position
        self.c = c
        self.eps = eps

    @property
    def n_users(self) -> int:
        return self.codewords.shape[0]

    @property
    def m(self) -> int:
        return self.codewords.shape[1]

    def codeword(self, user_index: int, m: int | None = None) -> np.ndarray:
        """This user's bits, truncated to the ``m`` positions a document can carry.

        A document only carries as many fingerprint positions as it has slots,
        so the code is generated per-document at that length and the codeword is
        taken from the front. Truncating rather than resampling matters: the
        same user's first ``m`` bits must be identical for a short document and
        a long one, or two copies from one recipient would carry unrelated
        fingerprints and the scores could not be pooled.
        """
        row = self.codewords[user_index]
        return row[:m] if m is not None else row

    @classmethod
    def generate(cls, n_users: int, c: int = 3, eps: float = 1e-6,
                 m: int | None = None, seed: int | None = None) -> "TardosCode":
        rng = np.random.default_rng(seed)
        m = m or code_length(n_users, c, eps)
        # Two independent streams, both seeded from ``seed`` up front. The bias
        # draw consumes exactly ``m`` values, so sharing one stream would move
        # the bit draw to a different starting offset for every ``m`` -- and the
        # prefix property below, which is the whole point of drawing
        # position-major, would silently fail again.
        bias_rng = np.random.default_rng(int(rng.integers(0, 2 ** 63)))
        bit_rng = np.random.default_rng(int(rng.integers(0, 2 ** 63)))
        # cutoff t keeps biases away from 0/1 (Tardos: t = 1/(300 c)); relaxed here
        t = 1.0 / (10 * c)
        lo, hi = math.asin(math.sqrt(t)), math.pi / 2 - math.asin(math.sqrt(t))
        r = bias_rng.uniform(lo, hi, size=m)
        p = np.sin(r) ** 2                                  # arcsine-distributed biases
        # Drawn position-major -- ``(m, n_users)`` then transposed -- rather than
        # ``(n_users, m)`` directly. This is what makes the promise in
        # :meth:`codeword` actually true: a document only carries as many
        # fingerprint positions as it has slots, so the code is regenerated per
        # document at that length from the same stored seed, and the positions
        # two such codes share must be identical or a recipient's short-document
        # copy and long-document copy would carry unrelated fingerprints and
        # their scores could not be pooled. Filling row-major in
        # ``(n_users, m)`` order makes every row start at a different offset once
        # ``m`` changes, which silently breaks exactly that.
        bits = (bit_rng.random((m, n_users)) < p[:, None]).astype(np.uint8)
        return cls(np.ascontiguousarray(bits.T), p, c, eps)

    # --- accusation ---------------------------------------------------------

    def _weights(self) -> tuple[np.ndarray, np.ndarray]:
        # symmetric score contributions g1 (bit=1) and g0 (bit=0)
        g1 = np.sqrt((1 - self.p) / self.p)
        g0 = -np.sqrt(self.p / (1 - self.p))
        return g1, g0

    def scores(self, y: np.ndarray,
               observed: np.ndarray | None = None) -> np.ndarray:
        """Accusation score per user for an extracted (possibly noisy) sequence y.

        Symmetric scoring: for position j, user with bit x contributes
          y=1: x? +g1 : -g1'      y=0: x? -g0' : +g0
        collapsed into the standard symmetric form below.

        ``y`` is scored over **its own length**, using the first ``len(y)``
        biases and codeword columns. That is not a convenience: a document
        carries only as many fingerprint positions as it has slots, so the
        extracted sequence is always a prefix of the code -- the object handed
        to the investigator is generated at the formal length (see
        :meth:`codeword`). Scoring it against the full-length ``p`` broadcasts
        two different shapes and raises, which is how this was found; scoring it
        against the full-length code silently, had the shapes happened to match,
        would have been worse.

        ``observed`` masks the positions the extractor actually read -- see
        :meth:`threshold` for why scoring unobserved positions is not merely
        wasteful but wrong. ``None`` scores every position, which is correct only
        when the caller knows the whole document was read.

        A ``y`` longer than the code is a caller error rather than something to
        absorb, because it means the extraction produced positions nobody was
        ever marked at.
        """
        y = np.asarray(y, dtype=np.float64)
        m = y.size
        if m > self.m:
            raise ValueError(
                f"cannot score {m} positions against a code of length {self.m}")
        if m == 0:
            return np.zeros(self.n_users)

        if observed is not None:
            keep = np.asarray(observed, dtype=bool)[:m]
            idx = np.nonzero(keep)[0]
            if idx.size == 0:
                # Nothing was read. Every user scores zero rather than every
                # user scoring whatever the unobserved positions happened to
                # look like.
                return np.zeros(self.n_users)
            y = y[idx]
            p = self.p[idx]
            X = self.codewords[:, idx].astype(np.float64)
        else:
            p = self.p[:m]
            X = self.codewords[:, :m].astype(np.float64)

        g1 = np.sqrt((1 - p) / p)
        g0 = np.sqrt(p / (1 - p))
        # per-position contribution given user bit x and colluded bit y
        # x=1,y=1 -> +g1 ; x=0,y=1 -> -g0 ; x=1,y=0 -> -g1 ; x=0,y=0 -> +g0
        pos = X * (y * g1 - (1 - y) * g1) + (1 - X) * (-y * g0 + (1 - y) * g0)
        return pos.sum(axis=1)

    def threshold(self, m: int | None = None) -> float:
        """Accusation threshold Z (symmetric Tardos): ``c*sqrt(m*ln(n/eps))``.

        ``m`` defaults to the full code length but must be passed whenever the
        scored sequence is shorter: the score is a sum over the positions that
        were actually read, so the threshold it is compared against has to be
        scaled to the same count. Using the full-length threshold against a
        prefix makes the bar grow with the square root of positions that do not
        exist, and a real colluder can then never clear it however strong the
        evidence.

        "Actually read" is the operative phrase, and it is why ``scores`` takes
        an ``observed`` mask. A fragment of a document leaves most positions
        unread, and the extractor reports those with ``totals == 0``; turning
        that into a hard bit 0 and summing it as though it were evidence scores
        positions nobody looked at. The effect was measured and is large: a
        seven-tenths fragment of a recipient's own marked copy scored **1.4-1.5
        Z**, higher than the whole copy, because the unread remainder defaulted
        to bits that happened to suit that codeword. Masking those positions and
        scaling ``m`` to the count actually read is what makes a partial
        observation score like a partial observation.
        """
        m = self.m if m is None else m
        if m <= 0:
            return 0.0
        return self.c * math.sqrt(m * math.log(self.n_users / self.eps))

    def accuse(self, y: np.ndarray) -> list[tuple[int, float]]:
        """Return users whose score exceeds the threshold, highest score first."""
        y = np.asarray(y)
        s = self.scores(y)
        Z = self.threshold(y.size)
        hits = [(int(i), float(s[i])) for i in range(self.n_users) if s[i] > Z]
        hits.sort(key=lambda t: -t[1])
        return hits

    def rank(self, y: np.ndarray, top: int = 5) -> list[tuple[int, float]]:
        """Always return the top-k by score (for ranked-candidate reporting)."""
        s = self.scores(y)
        order = np.argsort(-s)[:top]
        return [(int(i), float(s[i])) for i in order]


# --------------------------------------------------------------------------
# Detecting *that* a collusion happened
# --------------------------------------------------------------------------
#
# ``TardosCode.accuse`` answers "who did it" and is deliberately conservative: at
# the code lengths a normal document supports, a real colluder's score sits at a
# fraction of Z (see the README's measured table), so accuse() names nobody --
# correctly, since naming a person is a strong claim. The leak-check still has to
# decide what a fragment *is*, though, because that decides both the status it
# reports and whether it falls back to the ledger list.
#
# The tempting rule -- "the trace produced a ranking, so call it a collusion" --
# is wrong, because ``rank`` returns every user ranked, always. It fires on an
# unmarked copy of the plaintext. The next tempting rule, "two users are
# elevated", is also wrong, and less obviously so: a splice only differs from
# either copy at positions where the two codewords differ, and the arcsine bias
# puts most positions near p=0 or p=1, where two users usually share a bit. So a
# splice is decided by a few dozen positions, and the mixture can resolve almost
# entirely in one colluder's favour -- measured, a real splice scoring
# [0.12, 0.75, 0.16, 0.16] of Z, one colluder clear and the other in the noise.
#
# What holds across both is that a fragment carrying *no* mark stays low, while
# anything carrying a mark does not. Measured on the synthetic corpus (4 users,
# ~1865-word documents, ~116 Tardos positions, scores masked to the positions
# the extractor actually read):
#
#   population                                  n     top/Z
#   unmarked copy of the plaintext              7     [0.02, 0.24]
#   fragment too short to reach the region      8     no positions read
#   one recipient's marked copy, whole          4     [1.28, 1.70]
#   one recipient's marked copy, 35% fragment   2     [0.84, 0.87]
#   splice of two colluders, mixed             40     [0.65, 1.14]
#
# ``MARK_PRESENT`` sits in the gap between the unmarked population and everything
# that carries a mark.
#
# ``USER_ELEVATED`` decides between "a mark belonging to one person" and "a
# mixture", and it is the weaker of the two separations: within a splice the
# lower colluder was measured from 0.23 to 0.85 of Z, while the highest-scoring
# *innocent* in a splice reached 0.30. A colluder who happens to sit below the
# cut is not lost -- they are still ranked, still carry their score, and in every
# case measured the top-ranked user was a real colluder -- but the report says
# "one user's mark" rather than "a collusion". The error is deliberately in that
# direction: calling a mixture a single mark understates what is known, while
# calling a single mark a collusion states something false about people.
#
# ``tests/test_collusion_indicator.py`` re-measures both populations, so a change
# to the corpus, the code length or the user count cannot silently invalidate
# these numbers.
MARK_PRESENT = 0.40     # top/Z at or above which some mark is present at all
USER_ELEVATED = 0.35    # a user at or above this fraction of Z is "elevated"

NO_MARK = "no-mark"
SINGLE_USER = "single-user"
COLLUSION = "collusion"


def classify_scores(scores: np.ndarray, z: float) -> str:
    """Say what a Tardos score vector is evidence of: ``NO_MARK``, ``SINGLE_USER``
    or ``COLLUSION``.

    Deliberately three answers rather than a boolean, because the two ways of
    *not* being a collusion are different things to report: no mark at all means
    the fragment carries no fingerprint, while a single elevated user is a mark
    that belongs to one person -- evidence, just not evidence of collusion.

    Returns ``NO_MARK`` when there is no threshold to compare against, which is
    what a document too short to carry Tardos positions yields.
    """
    if z <= 0:
        return NO_MARK
    s = np.asarray(scores, dtype=np.float64)
    if s.size == 0:
        return NO_MARK
    top = float(s.max()) / z
    if top < MARK_PRESENT:
        return NO_MARK
    if colluders_above(s, z) >= 2:
        return COLLUSION
    # One elevated user. A whole marked copy of a single recipient and a fragment
    # of one both look like this, and so does a splice that resolved almost
    # entirely in one colluder's favour -- those were measured and are not
    # separable from the score vector alone, so the honest answer is the one that
    # overstates least.
    return SINGLE_USER


def colluders_above(scores: np.ndarray, z: float,
                    cut: float = USER_ELEVATED) -> int:
    """How many users score at or above ``cut`` times the accusation threshold."""
    if z <= 0:
        return 0
    s = np.asarray(scores, dtype=np.float64)
    return int(np.count_nonzero(s >= cut * z))
