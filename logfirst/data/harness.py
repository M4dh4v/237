"""OCR degradation harness: render, degrade, OCR, measure.

Every capacity and robustness claim in this repository is supposed to be backed
by a number this module produced, on a fixed seed, rather than by an assumption.
The build specification is explicit about it -- "validate this empirically
against your synthetic corpus rather than assuming it" -- and this is where that
happens.

What is simulated here, stated plainly: we render documents with Pillow using a
system font and apply a catalogue of degradations (JPEG recompression,
downscaling, blur, contrast loss). This is a *model* of what happens to a
screenshot, not a real phone photo of a real screen. The measured bit-error
rates are therefore a lower bound on real-world damage -- a photograph adds
perspective distortion, uneven lighting and sensor noise that none of these
transforms reproduce. The pipeline's robustness to the transforms here should not
be read as robustness to an arbitrary photograph.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..forensics import align
from ..watermark import linguistic, ocr, payload


def _font(size: int = 17):
    for path in ("/usr/share/fonts/dejavu/DejaVuSerif.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render(text: str, width: int = 1000, font_size: int = 17,
           margin: int = 40, line_gap: int = 7) -> Image.Image:
    """Lay the text out on a white page and rasterise it."""
    font = _font(font_size)
    tmp = Image.new("RGB", (width, 10), "white")
    d = ImageDraw.Draw(tmp)

    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        line = ""
        for w in words:
            probe = f"{line} {w}".strip()
            if d.textlength(probe, font=font) > width - 2 * margin:
                lines.append(line)
                line = w
            else:
                line = probe
        if line:
            lines.append(line)
        lines.append("")

    line_h = font_size + line_gap
    img = Image.new("RGB", (width, margin * 2 + line_h * max(1, len(lines))),
                    "white")
    d = ImageDraw.Draw(img)
    y = margin
    for line in lines:
        d.text((margin, y), line, fill=(20, 20, 20), font=font)
        y += line_h
    return img


# --------------------------------------------------------------------------
# Degradations
# --------------------------------------------------------------------------

def jpeg(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def downscale(img: Image.Image, factor: float) -> Image.Image:
    w, h = img.size
    small = img.resize((max(1, int(w * factor)), max(1, int(h * factor))),
                       Image.LANCZOS)
    return small.resize((w, h), Image.LANCZOS)


def blur(img: Image.Image, radius: float) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def contrast(img: Image.Image, factor: float) -> Image.Image:
    from PIL import ImageEnhance
    return ImageEnhance.Contrast(img).enhance(factor)


def rotate(img: Image.Image, degrees: float) -> Image.Image:
    return img.rotate(degrees, resample=Image.BICUBIC, expand=True,
                      fillcolor="white")


@dataclass
class Attack:
    name: str
    fn: object
    note: str = ""


CATALOG: dict[str, Attack] = {
    "clean": Attack("clean", lambda im: im, "no degradation"),
    "jpeg85": Attack("jpeg85", lambda im: jpeg(im, 85),
                     "mild recompression"),
    "jpeg50": Attack("jpeg50", lambda im: jpeg(im, 50),
                     "typical chat-app recompression"),
    "jpeg30": Attack("jpeg30", lambda im: jpeg(im, 30),
                     "aggressive recompression"),
    "resize60": Attack("resize60", lambda im: downscale(im, 0.6),
                       "screenshot rescaled to a smaller viewport"),
    "blur1": Attack("blur1", lambda im: blur(im, 1.0), "slight defocus"),
    "contrast70": Attack("contrast70", lambda im: contrast(im, 0.7),
                         "washed-out capture"),
    "rot1": Attack("rot1", lambda im: rotate(im, 1.0), "1-degree skew"),
    "combo": Attack("combo",
                    lambda im: blur(contrast(jpeg(downscale(im, 0.75), 60), 0.85), 0.6),
                    "several at once, closer to a photographed screen"),
}


# --------------------------------------------------------------------------
# Measurement
# --------------------------------------------------------------------------

@dataclass
class BERResult:
    doc_id: str
    attack: str
    n_bits: int
    bit_errors: int
    ber: float
    slots: int
    slots_observed: int
    channel_errors: int
    channel_ber: float
    aligned_fraction: float
    pointer_ok: bool
    pointer_value: int | None
    pointer_expected: int
    guarantee: str = "none"
    notes: list[str] = field(default_factory=list)


def measure_document(doc: dict, ledger_index: int, seed: bytes,
                     attacks: list[str] | None = None,
                     tardos_len: int = 0, n_users: int = 0,
                     render_kw: dict | None = None) -> list[BERResult]:
    """Embed a payload in one document and measure error rates under each attack.

    Two rates are reported and they mean different things, which is why both are
    kept:

    * ``channel_ber`` -- the fraction of *carrier slots* whose OCR'd word differs
      from the synonym actually embedded. This is the raw channel and it is the
      number the capacity argument rests on; it is measured before any coding
      gain.
    * ``ber`` -- the fraction of *payload* bits wrong after per-position majority
      voting. This is what the decoder sees, and it is much lower than the
      channel rate by design.
    """
    attacks = attacks or ["clean", "jpeg50", "resize60", "combo"]
    text = doc["text"]
    slots = linguistic.slot_count(text)
    n_tardos = 0
    if tardos_len:
        n_tardos = payload.plan(slots, tardos_len, n_users=n_users)["tardos_bits"]
    rng = np.random.default_rng(1234)
    tardos_bits = rng.integers(0, 2, n_tardos, dtype=np.uint8) if n_tardos else None
    bits = payload.build_payload(ledger_index, tardos_bits)

    marked, used = linguistic.embed(text, bits, seed)
    plan = payload.plan(slots, tardos_len, n_users=n_users)
    # The words actually written, so channel error can be measured against what
    # was embedded rather than against the canonical original (which differs at
    # every slot the keystream flipped).
    written = {o: linguistic.GROUPS[g][v] for o, g, v in
               linguistic.carrier_slots(marked)}
    img = render(marked, **(render_kw or {}))

    out = []
    for name in attacks:
        atk = CATALOG[name]
        degraded = atk.fn(img)
        leaked = ocr.image_to_text(degraded)
        mapping = align.align(text, leaked)

        ch_err = ch_obs = 0
        for ordinal, target in written.items():
            w = mapping.get(ordinal)
            if w is None:
                continue
            ch_obs += 1
            if w.lower() != target.lower():
                ch_err += 1

        votes, totals = linguistic.extract(text, mapping, seed, len(bits))
        rec = (votes * 2 > totals).astype(np.uint8)
        seen = totals > 0
        if seen.any():
            errs = int(np.sum((rec != bits) & seen))
            ber = errs / int(seen.sum())
        else:
            errs, ber = 0, 1.0
        idx, conf, _ = payload.decode_pointer(rec, totals)
        out.append(BERResult(
            doc_id=doc["doc_id"], attack=name, n_bits=len(bits),
            bit_errors=errs, ber=ber, slots=slots,
            slots_observed=int(seen.sum()),
            channel_errors=ch_err, channel_ber=ch_err / max(1, ch_obs),
            aligned_fraction=align.coverage(text, mapping),
            pointer_ok=(idx == ledger_index), pointer_value=idx,
            pointer_expected=ledger_index, guarantee=plan["guarantee"],
            notes=[atk.note]))
    return out


def summarize(results: list[BERResult]) -> dict:
    """Aggregate a run, grouped by attack."""
    by: dict[str, list[BERResult]] = {}
    for r in results:
        by.setdefault(r.attack, []).append(r)
    out = {}
    for name, rs in by.items():
        ok = sum(1 for r in rs if r.pointer_ok)
        out[name] = {
            "n": len(rs),
            "pointer_recovered": ok,
            "pointer_rate": round(ok / len(rs), 3),
            "mean_ber": round(sum(r.ber for r in rs) / len(rs), 4),
            "max_ber": round(max(r.ber for r in rs), 4),
            "mean_channel_ber": round(
                sum(r.channel_ber for r in rs) / len(rs), 4),
            "max_channel_ber": round(max(r.channel_ber for r in rs), 4),
            "mean_aligned": round(sum(r.aligned_fraction for r in rs) / len(rs), 3),
        }
    return out


def run(n_docs: int = 6, target_words: int = 1800, seed: int = 7,
        attacks: list[str] | None = None, density: float = 1 / 10.0,
        tardos_len: int = 0, n_users: int = 0) -> tuple[list[BERResult], dict]:
    from . import corpus
    docs = corpus.make_document_set(n_docs, seed=seed, target_words=target_words,
                                    density=density)
    rng = random.Random(seed)
    all_results = []
    for i, doc in enumerate(docs):
        wm_seed = bytes(rng.getrandbits(8) for _ in range(32))
        all_results += measure_document(doc, 1000 + i, wm_seed, attacks=attacks,
                                        tardos_len=tardos_len, n_users=n_users)
    return all_results, summarize(all_results)
