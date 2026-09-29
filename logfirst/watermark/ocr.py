"""OCR: turning a leaked screenshot back into text.

This is the front door of the leak-check pipeline and the stage that decides how
much of the watermark survives at all, so it is worth being explicit about what
it is and is not.

We shell out to the system ``tesseract`` binary. It is a genuine, widely
deployed OCR engine, not a stub -- the point of the exercise is that the
watermark must survive a *real* OCR pass, and a round trip through our own
lossless text encoding would prove nothing.

Two honest limitations:

* **Segmentation, not recognition, is the main error source.** Tesseract
  occasionally merges or splits words ("budget allocation" -> "budgetallocation"
  is a real observed output). A merged pair removes a carrier slot; the
  redundancy and RS erasure handling downstream are what absorb that, and
  tests/test_ocr_harness.py measures how often it happens rather than assuming
  it away.
* **Reading order is not preserved.** We return words in the engine's own order.
  That is fine here because the extractor aligns against the canonical text
  rather than trusting position, but it does mean the returned string is not
  necessarily the document's prose in order, and must not be shown to a user as
  if it were the leaked text verbatim.

Rendering text to an image for the round-trip test lives in
``data/harness.py``; this module only reads images.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile

from PIL import Image


class OCRError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("tesseract") is not None


def image_to_text(img: Image.Image, psm: int = 6) -> str:
    """OCR an image to a whitespace-joined word string.

    ``--psm 6`` ("assume a single uniform block of text") rather than the
    default page-segmentation mode: leaked fragments are typically a paragraph
    or a screenshot of one, and the default mode spends effort looking for
    columns and headers that are not there.
    """
    if not available():
        raise OCRError(
            "tesseract is not installed; install it (Fedora: 'dnf install "
            "tesseract') or install pytesseract's binary dependency. The OCR "
            "path cannot be stubbed -- the watermark's whole claim is that it "
            "survives a real OCR pass.")

    try:
        import pytesseract
        return " ".join(pytesseract.image_to_string(
            img.convert("RGB"), config=f"--psm {psm}").split())
    except ImportError:
        pass

    # Fall back to the binary directly so the pipeline does not depend on the
    # Python wrapper being installed.
    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as f:
        img.convert("RGB").save(f.name, format="PNG")
        proc = subprocess.run(["tesseract", f.name, "-", "--psm", str(psm)],
                              capture_output=True, text=True)
    if proc.returncode != 0:
        raise OCRError(f"tesseract failed: {proc.stderr.strip()}")
    return " ".join(proc.stdout.split())


def bytes_to_image(raw: bytes) -> Image.Image:
    return Image.open(io.BytesIO(raw)).convert("RGB")
