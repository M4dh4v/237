"""Document identification: which document did this fragment come from?

The leak-check front end does not know, a priori, which document a pasted
paragraph or screenshot belongs to. The watermark can only be read *relative to
a canonical original* -- extraction works by differencing the leaked text against
the document's own carrier slots -- so identification has to happen first and
everything downstream depends on it being right. That makes this stage's failure
mode worth stating: pick the wrong document and the extractor will happily
produce bits, because it is differencing against the wrong slot positions. The
bits will be noise, the pointer will fail to decode, and the pipeline will report
"no attribution" rather than a wrong name -- which is the correct outcome, but
it means a low identification confidence must be surfaced, not hidden.

TF-IDF cosine over word n-grams. Deliberately not a transformer: at corpus sizes
a demo can hold, TF-IDF is as accurate, needs no model download, runs offline in
milliseconds, and -- the real reason -- its similarity score is interpretable
enough to justify the confidence number shown to an analyst. A transformer's
cosine is no more meaningful, just slower.

The ambiguity rule matters more than the ranking: if the top two candidates are
close, both are returned. Silently picking the higher one would let a fragment
that genuinely straddles two documents produce a confident-looking single
answer, which is exactly the failure the honesty requirements forbid.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-z]+")


def _norm(text: str) -> str:
    return " ".join(w.lower() for w in _TOKEN.findall(text))


class DocumentIndex:
    """A TF-IDF index over canonical documents."""

    def __init__(self, docs: list[dict]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.docs = list(docs)
        self.ids = [d["doc_id"] for d in self.docs]
        # (1,2) word n-grams: unigrams alone are too weak on short fragments,
        # higher orders too sparse once OCR drops or merges a word.
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True,
                                   lowercase=True, stop_words=None)
        self.matrix = self.vec.fit_transform([_norm(d["text"]) for d in self.docs])

    def identify(self, query: str, top_k: int = 3,
                 ambiguity_margin: float = 0.08) -> list[dict]:
        """Rank documents by similarity. Returns every candidate within
        ``ambiguity_margin`` of the best score, so a genuinely ambiguous
        fragment surfaces more than one option.

        A single-element list means the match was unambiguous by this margin --
        not that it is certainly correct. The caller reports the score.
        """
        from sklearn.metrics.pairwise import cosine_similarity

        q = self.vec.transform([_norm(query)])
        sims = cosine_similarity(q, self.matrix)[0]
        order = sims.argsort()[::-1]
        ranked = [{"doc_id": self.ids[i], "score": float(sims[i]),
                   "text": self.docs[i]["text"]} for i in order[:max(top_k, 1)]]
        if not ranked:
            return []
        best = ranked[0]["score"]
        if best <= 0:
            return [ranked[0]]
        near = [r for r in ranked if r["score"] >= best - ambiguity_margin]
        return near

    def best(self, query: str) -> tuple[dict | None, list[dict]]:
        """``(best candidate or None, all near-ties)``."""
        cands = self.identify(query)
        if not cands:
            return None, []
        return cands[0], cands


# Below this cosine score the fragment is not plausibly from this corpus at all,
# and the pipeline should say "unidentified" rather than proceed to extract bits
# from the least-bad match.
#
# Measured, not chosen -- tests/test_identify.py re-derives these bands. Cosine
# over (1,2)-grams is never near zero for English prose, because ordinary words
# appear in the corpus too, so a floor picked by intuition is nearly always too
# low. 300 out-of-corpus samples (150-400 word chunks of unrelated technical
# prose) score 0.063-0.201; in-corpus fragments score 0.307 and up at 30 words,
# 0.412 at 60, and 0.636 at 200. 0.25 sits in the gap: above every out-of-corpus
# sample measured, below every in-corpus one.
#
# It is a floor on *plausibility*, not a statement of confidence. A 30-word
# fragment scoring 0.31 clears it and is identified correctly only about four
# times in five, which is why the score is reported alongside the name rather
# than replaced by a boolean -- see `Investigation.doc_confidence`.
MIN_IDENTIFY_SCORE = 0.25
