"""Payload coding: Reed-Solomon over the ledger pointer, Tardos alongside it.

The bits that ride the linguistic slots are a concatenation of two very
different things, and the difference dictates how each is decoded.

**The ledger pointer** is a small integer -- which ledger entry released this
copy -- protected by Reed-Solomon. It is the part that identifies the *session*,
and because it names an entry that the recipient's own key signed, recovering it
is what turns a leaked paragraph into a named signer. RS is here for OCR noise:
character confusions and alignment slips corrupt individual bits, and RS repairs
them from parity. Crucially, slots that extraction could not read at all become
*erasures* rather than guessed bits, which costs one parity symbol instead of
two -- see the erasure handling in :func:`decode_pointer`.

**The Tardos codeword** is a per-recipient pseudorandom string, and it is what
survives a *collusion*. If two recipients splice their copies together, the
pointer may decode to one of them or to neither, but the mixture of two Tardos
codewords still correlates with both, and tracing names real colluders rather
than a single falsely accused one. Tardos bits are deliberately *not* RS-coded:
they carry no redundancy by design, because their power comes from the
correlation statistic over many positions, and adding structure would only give
a colluder something to attack.

Both share the same slots, so they compete for capacity. :func:`plan` is the one
place that decides the split, so the trade-off is visible in a single function
rather than scattered across embed and extract.
"""

from __future__ import annotations

import numpy as np
from reedsolo import RSCodec, ReedSolomonError

from .tardos import code_length

# 2 bytes of index covers 65 536 ledger entries, which is far more than a demo
# needs and keeps the pointer block small enough to fit a short document.
# Widen to 3 or 4 bytes if the ledger is expected to exceed that; the verifier
# and extractor both read the width from here.
POINTER_BYTES = 2
POINTER_ECC = 3
POINTER_BITS = (POINTER_BYTES + POINTER_ECC) * 8   # 40

# Repetition for the pointer block. Measured, not guessed: the harness in
# ``data/harness.py`` puts the per-slot channel error rate at 0.0015-0.0047
# across the degradation catalogue on seed 7 (see README "Watermark capacity").
# At p=0.008 a 3-fold majority vote leaves a per-bit error of ~1.9e-4 and a
# 5-fold one of ~5.1e-6; against RS(3) over 5 bytes both are comfortable, so 3
# is the floor we accept and documents offering less are refused rather than
# weakly marked. The rate used for the budget is deliberately the pessimistic
# one, well above what was measured, because the cost of under-provisioning is a
# document that looks marked and is not.
MIN_REPETITION = 3
MIN_SLOTS = POINTER_BITS * MIN_REPETITION


def _rs() -> RSCodec:
    return RSCodec(POINTER_ECC)


def encode_pointer(index: int) -> np.ndarray:
    """RS-encode the ledger index into ``POINTER_BITS`` bits, MSB first."""
    if not 0 <= index < (1 << (8 * POINTER_BYTES)):
        raise ValueError(f"ledger index {index} does not fit in "
                         f"{POINTER_BYTES} bytes")
    raw = index.to_bytes(POINTER_BYTES, "big")
    return np.unpackbits(np.frombuffer(bytes(_rs().encode(raw)), dtype=np.uint8)
                         ).astype(np.uint8)


def decode_pointer(bits: np.ndarray, totals: np.ndarray | None = None
                   ) -> tuple[int | None, float, int]:
    """Decode the pointer. Returns ``(index or None, confidence, erasures)``.

    ``totals[j] == 0`` means no slot voted at payload position ``j``, so the
    byte containing it is handed to RS as an *erasure*: the decoder is told the
    symbol is missing rather than being given a bit we do not believe. With 3
    parity symbols, RS can repair any 3 erasures, or 1 error plus 1 erasure --
    erasures are strictly cheaper, which is why the soft information is kept
    this far down the pipeline instead of being hardened early.
    """
    bits = np.asarray(bits, dtype=np.uint8).ravel()[:POINTER_BITS]
    if bits.size < POINTER_BITS:
        bits = np.concatenate([bits, np.zeros(POINTER_BITS - bits.size,
                                              dtype=np.uint8)])
    nbytes = POINTER_BITS // 8

    erase_pos = []
    if totals is not None:
        totals = np.asarray(totals).ravel()[:POINTER_BITS]
        for b in range(nbytes):
            chunk = totals[b * 8:(b + 1) * 8]
            if chunk.size and np.any(chunk == 0):
                erase_pos.append(b)
    if len(erase_pos) > POINTER_ECC:
        return None, 0.0, len(erase_pos)

    data = bytearray(np.packbits(bits).tobytes())
    try:
        decoded, _, errata = _rs().decode(data, erase_pos=erase_pos or None)
    except ReedSolomonError:
        return None, 0.0, len(erase_pos)
    if not decoded:
        return None, 0.0, len(erase_pos)

    index = int.from_bytes(bytes(decoded[:POINTER_BYTES]), "big")
    n_repaired = len(errata) if errata is not None else 0
    conf = max(0.0, 1.0 - n_repaired / (POINTER_ECC + 1))
    return index, conf, len(erase_pos)


def plan(n_slots: int, tardos_len: int = 0, *, n_users: int = 0,
         max_colluders: int = 2, eps: float = 1e-3) -> dict:
    """Decide the payload layout for a document with ``n_slots`` slots.

    Returns ``{"ok", "pointer_bits", "pointer_slots", "tardos_bits",
    "total_bits", "repetition", "tardos_required", "guarantee", "reason"}``.

    The pointer always gets its full block at no less than
    :data:`MIN_REPETITION`. Tardos takes what is left, and only if a *useful*
    amount is left -- a Tardos code of a handful of positions produces
    confident-looking scores with no statistical power behind them.

    ``guarantee`` is the honest part, and it is the reason this function takes
    ``n_users``/``max_colluders``/``eps`` at all. Tardos' provable
    false-accusation bound holds only above :func:`tardos.code_length`, which for
    even a modest user count is far more positions than a normal document
    offers. Measurements in tests/test_tardos.py (summarised in README) show that
    a *shorter* code still ranks true colluders at the top essentially always,
    but its scores do not cross the formal accusation threshold. So:

    * ``"formal"`` -- the code meets the length the bound requires. A suspect
      crossing the threshold is an accusation with a stated false-positive rate.
    * ``"ranking-only"`` -- shorter than that. Suspects may be *ranked* and their
      scores reported, but the bound does not apply and no single name may be
      presented as an accusation. Callers must surface this; investigate.py does.
    * ``"none"`` -- no Tardos positions at all. Attribution rests on the ledger
      pointer alone.
    """
    if n_slots < MIN_SLOTS:
        return {"ok": False, "pointer_bits": POINTER_BITS, "pointer_slots": 0,
                "tardos_bits": 0, "total_bits": POINTER_BITS, "repetition": 0,
                "tardos_required": 0, "guarantee": "none",
                "reason": f"only {n_slots} slots; {MIN_SLOTS} needed to carry a "
                          f"pointer at {MIN_REPETITION}x repetition"}

    pointer_slots = POINTER_BITS * MIN_REPETITION
    room = n_slots - pointer_slots
    want = min(tardos_len, room) if tardos_len else 0
    tardos_bits = want if want >= MIN_TARDOS else 0
    total = POINTER_BITS + tardos_bits

    required = code_length(n_users, max_colluders, eps) if n_users else 0
    if not tardos_bits:
        guarantee = "none"
    elif required and tardos_bits >= required:
        guarantee = "formal"
    else:
        guarantee = "ranking-only"

    if tardos_bits:
        reason = ""
    elif tardos_len == 0:
        reason = "pointer-only: no Tardos code requested"
    else:
        reason = (f"only {room} slots left for Tardos, below the "
                  f"{MIN_TARDOS}-position floor; marked pointer-only")

    return {"ok": True, "pointer_bits": POINTER_BITS,
            "pointer_slots": pointer_slots, "tardos_bits": tardos_bits,
            "total_bits": total, "repetition": n_slots // total,
            "tardos_required": required, "guarantee": guarantee,
            "reason": reason}


# Below this, Tardos scores have no statistical power and a "top suspect" would
# be noise wearing a number. Chosen so that the accusation threshold is at least
# a few times the per-position score scale; tests/test_tardos.py measures the
# false-accusation behaviour at and below it.
MIN_TARDOS = 64


def plan_for_document(n_slots: int, n_users: int, max_colluders: int = 2,
                      eps: float = 1e-3) -> dict:
    """The layout *both* the marker and the investigator must use.

    The investigator only has the leaked text and the canonical document; it was
    not present when the copy was marked, so it cannot be told the payload length
    out of band. The layout therefore has to be a pure function of things both
    sides know -- the document's slot count and the deployment's user count --
    rather than a choice the marker makes freely. Marking with one layout and
    reading with another would silently produce noise, so this is the single
    entry point and both sides call it.
    """
    required = code_length(n_users, max_colluders, eps) if n_users else 0
    return plan(n_slots, tardos_len=required, n_users=n_users,
                max_colluders=max_colluders, eps=eps)


def build_payload(ledger_index: int, tardos_bits: np.ndarray | None = None
                  ) -> np.ndarray:
    """Concatenate the RS pointer and (optionally) a Tardos codeword."""
    parts = [encode_pointer(ledger_index)]
    if tardos_bits is not None and len(tardos_bits):
        parts.append(np.asarray(tardos_bits, dtype=np.uint8).ravel())
    return np.concatenate(parts).astype(np.uint8)


def split_payload(bits: np.ndarray, n_tardos: int) -> tuple[np.ndarray, np.ndarray]:
    """Split recovered bits back into ``(pointer_bits, tardos_bits)``."""
    bits = np.asarray(bits, dtype=np.uint8).ravel()
    return bits[:POINTER_BITS], bits[POINTER_BITS:POINTER_BITS + n_tardos]


def bits_to_str(bits: np.ndarray) -> str:
    return "".join(str(int(b)) for b in np.asarray(bits).ravel())
