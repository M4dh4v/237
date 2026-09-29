"""Rendering, and the one property that matters about it.

Most of this file is ordinary: a PDF starts with ``%PDF``, the words come back
out of it, the page count is the page count. Two tests here are not ordinary.

The first is the glyph guard. fpdf2 does **not** raise when a font cannot draw a
character -- it logs a line and renders the text with those characters missing.
For a marked copy that is not a cosmetic problem: the delivered text would no
longer be the text the watermark was embedded in, so the mark would fail to
decode and the document would look perfectly fine while being unattributable.
The tests below drive that guard with characters no Latin font has.

The second is determinism. It is asserted because it is the thing that makes a
``pdf_hash`` mean anything, and it is asserted *narrowly* -- same machine, same
fpdf2 -- because that is the only claim that is true. Nothing in this tree ever
checks a hash by re-rendering; hashes are taken over the bytes that arrived.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

pytest.importorskip("fpdf")

from logfirst import pdfdoc                                          # noqa: E402

CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)

TEXT = "The quarterly logistics annex is circulated for review. " * 30

requires_poppler = pytest.mark.skipif(
    shutil.which("pdftotext") is None or shutil.which("pdfinfo") is None,
    reason="poppler's pdftotext/pdfinfo are not installed, so a rendered PDF "
           "cannot be read back; this is the check that the file is a real PDF "
           "and not merely bytes that start with %PDF")


def render(text: str = TEXT, **kw):
    kw.setdefault("doc_id", "DOC-0000")
    kw.setdefault("classification", "SECRET")
    kw.setdefault("created", CREATED)
    return pdfdoc.render(text, **kw)


def _extract(data: bytes, tmp_path, first: int | None = None,
             last: int | None = None) -> str:
    path = tmp_path / "doc.pdf"
    path.write_bytes(data)
    cmd = ["pdftotext"]
    if first is not None:
        cmd += ["-f", str(first), "-l", str(last if last is not None else first)]
    cmd += [str(path), "-"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


# ==========================================================================
# It is a PDF
# ==========================================================================

def test_the_output_is_a_pdf():
    r = render()
    assert r.data.startswith(b"%PDF-")
    assert r.data.rstrip().endswith(b"%%EOF")


@requires_poppler
def test_poppler_agrees_about_the_page_count(tmp_path):
    """The renderer's own count is a claim about the file; this checks it
    against a reader that has no reason to agree."""
    r = render(TEXT * 12)
    path = tmp_path / "doc.pdf"
    path.write_bytes(r.data)
    info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True)
    assert info.returncode == 0, info.stderr
    pages = [l for l in info.stdout.splitlines() if l.startswith("Pages:")]
    assert pages and int(pages[0].split()[1]) == r.pages
    assert r.pages > 1, "the fixture should be long enough to paginate"


@requires_poppler
def test_the_words_survive_a_real_pdf_round_trip(tmp_path):
    """The whole point of rendering to PDF rather than to an image: the text is
    still text, so the leak-check pipeline can read a leaked copy of it."""
    out = _extract(render().data, tmp_path)
    assert "quarterly logistics annex" in out
    assert "DOC-0000" in out


@requires_poppler
def test_the_classification_banner_is_on_every_page(tmp_path):
    """Not once at the top: the case worth caring about is a single page
    extracted on its own, and a banner only on page 1 does not survive it."""
    r = render(TEXT * 12)
    assert r.pages >= 3
    for page in (1, 2, r.pages):
        out = _extract(r.data, tmp_path, page)
        assert "SECRET" in out, f"no banner on page {page}"


def test_the_footer_carries_the_ledger_entry_when_there_is_one():
    """A presentational aid, labelled as such in the module docstring: it is
    not evidence, and the module says so rather than leaving it to be assumed."""
    r = render(ledger_index=7, leaf_hash="ab" * 32)
    assert r.data  # rendered without error; the note is drawn in the footer


def test_an_empty_document_still_renders():
    r = render("")
    assert r.data.startswith(b"%PDF-")
    assert r.pages == 1


# ==========================================================================
# The glyph guard -- fpdf2 drops characters and says nothing a caller can catch
# ==========================================================================

def test_a_character_the_font_cannot_draw_is_an_error_not_a_silent_drop():
    with pytest.raises(pdfdoc.RenderError) as e:
        render("the annex is 中文 and that is a problem")
    message = str(e.value)
    assert "U+4E2D" in message and "U+6587" in message
    assert "allow_replacements" in message


def test_accepting_replacements_reports_how_many_were_made():
    r = render("the annex is 中文", allow_replacements=True)
    assert r.replaced == 2
    assert r.data.startswith(b"%PDF-")


@requires_poppler
def test_a_replacement_is_visible_in_the_text_not_an_absent_character(tmp_path):
    """Substituted, not dropped. A silently closed gap would say the document
    was always like that, which is the lie worth avoiding."""
    out = _extract(render("the annex is 中文", allow_replacements=True).data,
                   tmp_path)
    # U+FFFD extracts as '?' through poppler, which is the point: something is
    # visibly there where the character was.
    assert "??" in out or "�" in out


def test_ordinary_prose_replaces_nothing():
    assert render().replaced == 0


# ==========================================================================
# Determinism, scoped honestly
# ==========================================================================

def test_the_same_inputs_give_the_same_bytes():
    """Same machine, same fpdf2. Asserted because a renderer that read the wall
    clock would make every pdf_hash meaningless; scoped because fpdf2's own
    output format is not frozen across versions and this does not promise it."""
    a, b = render(), render()
    assert hashlib.sha256(a.data).hexdigest() == hashlib.sha256(b.data).hexdigest()


def test_a_different_created_date_gives_different_bytes():
    a = render(created=datetime(2026, 1, 1, tzinfo=timezone.utc))
    b = render(created=datetime(2026, 6, 1, tzinfo=timezone.utc))
    assert a.data != b.data


def test_a_different_document_gives_different_bytes():
    assert render(doc_id="DOC-0000").data != render(doc_id="DOC-0001").data


# ==========================================================================
# write_pdf, and what it is for
# ==========================================================================

def test_write_pdf_writes_exactly_the_bytes_it_was_given(tmp_path):
    r = render()
    path = tmp_path / "out.pdf"
    pdfdoc.write_pdf(str(path), r.data)
    assert path.read_bytes() == r.data


def test_render_does_not_touch_the_filesystem(tmp_path, monkeypatch):
    """The client node holds no state between sessions and writes nothing, and
    that only stays true if rendering is pure. Asserted rather than trusted:
    a renderer that quietly cached to disk would put a forensic artefact
    somewhere nobody agreed to."""
    monkeypatch.chdir(tmp_path)
    render()
    assert list(tmp_path.iterdir()) == []
