"""Synthetic corpus generation.

Documents are built to a **carrier density target**, not generated freely and
then measured. That distinction matters: if documents were arbitrary prose, the
number of watermark slots would be whatever English happened to provide, and
every downstream decision -- payload size, Reed-Solomon strength, Tardos code
length -- would be a function of luck. Generating to a stated density makes the
capacity question answerable before the fact, and
``data/harness.py`` measures whether the target was actually met.

The generator is honest about what it is: template prose, not natural language.
That is a real limitation of every capacity number in this repository, and
README says so. It is not a limitation of the *watermark*, which operates on
whatever carrier words are present; it means the measured densities are
achievable rather than typical.
"""

from __future__ import annotations

import random
import re

from ..watermark import linguistic
from ..watermark.linguistic import GROUPS

_TOKEN = re.compile(r"[A-Za-z]+")

# Sentence frames. Each has slots filled from the carrier lexicon plus ordinary
# connective words, so the prose reads like a report while guaranteeing that
# carrier words appear at a controllable rate.
_SUBJECTS = ["The committee", "The directorate", "The regional office",
             "The review board", "The planning group", "The audit team",
             "The northern district", "The operations centre",
             "The oversight panel", "The technical working group"]
_VERBS = ["approved", "reviewed", "questioned", "endorsed", "deferred",
          "examined", "supported", "rejected", "revised", "accepted"]
_OBJECTS = ["the quarterly estimates", "the revised schedule",
            "the projected shortfall", "the allocation framework",
            "the procurement plan", "the staffing proposal",
            "the infrastructure budget", "the compliance report"]
_TAILS = ["after a lengthy review", "following consultation with stakeholders",
          "in light of the updated figures", "subject to further examination",
          "during the closed session", "before the deadline",
          "against the advice of the treasury", "pending a legal opinion"]


def _words(text: str) -> list[str]:
    return _TOKEN.findall(text)


def _carrier_ratio(text: str) -> float:
    w = _words(text)
    if not w:
        return 0.0
    return linguistic.slot_count(text) / len(w)


def _sentence(rng: random.Random) -> str:
    return (f"{rng.choice(_SUBJECTS)} {rng.choice(_VERBS)} "
            f"{rng.choice(_OBJECTS)} {rng.choice(_TAILS)}.")


def _carrier_rich_sentence(rng: random.Random, n_carriers: int = 3) -> str:
    """A sentence deliberately built around carrier words.

    The carrier words are drawn from the lexicon and used as the sentence's
    content words, so they read as plausible vocabulary rather than being
    sprinkled on top of unrelated text.
    """
    picks = rng.sample(range(len(GROUPS)), n_carriers)
    words = [rng.choice(GROUPS[g]) for g in picks]
    frames = {
        2: [
            lambda w: f"Officials {w[0]} the revised {w[1]}.",
            lambda w: f"The panel will {w[0]} a {w[1]}.",
            lambda w: f"We should {w[0]} the {w[1]} today.",
        ],
        3: [
            lambda w: f"The report will {w[0]} the {w[1]} of the {w[2]}.",
            lambda w: f"Officials {w[0]} that the {w[1]} requires a {w[2]}.",
            lambda w: f"We must {w[0]} each {w[1]} before the {w[2]}.",
            lambda w: f"The board noted a {w[1]} change in the {w[2]}.",
            lambda w: f"They {w[0]} the {w[1]} and the {w[2]}.",
        ],
        4: [
            lambda w: f"The {w[0]} will {w[1]} a {w[2]} for the {w[3]}.",
            lambda w: f"Members {w[0]} the {w[1]} and the {w[2]} of the {w[3]}.",
        ],
    }
    table = frames.get(len(words)) or frames[3]
    return rng.choice(table)(words)


def make_document(rng: random.Random, target_words: int = 1200,
                  density: float = 1 / 10.0) -> str:
    """Build one document, steering to roughly ``density`` carriers per token.

    A feedback loop rather than a fixed mix of sentence types: after each
    sentence we compare the density so far against the target and pick the next
    sentence type to close the gap. A fixed mix cannot hit a target, because the
    filler sentences contain carrier words too and how many depends on which
    frames are drawn -- so the achieved density would drift with the seed and
    every capacity number downstream would inherit that drift.
    """
    paras = []
    total = 0
    while total < target_words:
        sentences: list[str] = []
        n_tokens = 0
        n_carriers = 0
        while n_tokens < 110:
            # Aim slightly high: filler sentences pull the ratio back down.
            want = density * 1.15
            cur = (n_carriers / n_tokens) if n_tokens else 0.0
            if cur < want:
                s = _carrier_rich_sentence(rng, n_carriers=rng.choice([2, 3, 3]))
            else:
                s = _sentence(rng)
            sentences.append(s)
            n_tokens += len(_words(s))
            n_carriers += linguistic.slot_count(s)
        paras.append(" ".join(sentences))
        total += sum(len(p.split()) for p in paras[-1:])
    return "\n\n".join(paras)


def make_document_set(n: int, seed: int = 7, target_words: int = 1200,
                      density: float = 1 / 10.0) -> list[dict]:
    """``n`` distinct documents, deterministic for a given seed."""
    rng = random.Random(seed)
    seen: set[str] = set()
    out = []
    for i in range(n):
        while True:
            text = make_document(rng, target_words=target_words, density=density)
            # Guard against two documents being near-identical, which would make
            # the identification stage's job artificially easy.
            first = " ".join(text.split()[:8])
            if first not in seen:
                seen.add(first)
                break
        out.append({"doc_id": f"DOC-{i:04d}", "text": text,
                    "classification": rng.choice(["SECRET", "CONFIDENTIAL",
                                                  "RESTRICTED", "INTERNAL"]),
                    "slots": linguistic.slot_count(text),
                    "words": len(text.split())})
    return out


# A distinct persona pool so the same corpus can be regenerated with different
# prose while keeping document ids stable.
def density_report(docs: list[dict]) -> dict:
    if not docs:
        return {"n": 0}
    den = [d["slots"] / max(1, d["words"]) for d in docs]
    slots = [d["slots"] for d in docs]
    return {
        "n": len(docs),
        "mean_words": round(sum(d["words"] for d in docs) / len(docs), 1),
        "mean_slots": round(sum(slots) / len(slots), 1),
        "min_slots": min(slots),
        "max_slots": max(slots),
        "mean_density": round(sum(den) / len(den), 4),
        "words_per_marker": round(1 / (sum(den) / len(den)), 2),
    }
