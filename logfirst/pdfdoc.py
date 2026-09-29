"""Rendering a document to PDF.

There are two renderings in this system and the difference between them is the
whole point of the architecture:

* the **canonical** PDF, rendered by the distributor at seal time, which is what
  travels inside the ``.lfdoc`` envelope;
* the **marked** PDF, rendered on the recipient's side *after* the authority has
  released the key, whose text carries the linguistic watermark derived from
  that specific open's ledger entry.

The second cannot be produced at the first's time. The mark's seed is a hash of
a ledger entry that does not exist until someone asks to open the document, so
there is nothing to embed at distribution. :func:`render` takes the text it is
given and does not know which of the two it is producing; the difference is
entirely in the ``ledger_index``/``leaf_hash`` it is handed for the footer.

Two behaviours here are deliberate and would be bugs if they were the other way
round:

**A character the font cannot draw is an error, not a substitution.** fpdf2 does
not raise for this when a TrueType font is in use. It writes a line to a *logger*
and renders the text with the missing characters **removed**. (It is
``LOGGER.warning``, not ``warnings.warn``, so the obvious guard -- recording
warnings around the call -- catches nothing at all. That is why this module asks
the font's own character map what it can draw, up front, instead of trying to
notice afterwards.) If a dropped character reached a marked copy, the delivered
text would no longer be the text the watermark was embedded in, and the recovered
mark would fail to decode. The result would be a document that looks fine and
quietly cannot be attributed, which is the exact failure this system exists to
make impossible. So :func:`render` fails loudly and names the characters, unless
the caller has explicitly accepted substitutions -- and then it substitutes a
visible replacement character rather than letting the glyph vanish, so the page
shows that something was lost.

**``created`` is required.** A renderer that reads the wall clock is a renderer
whose output cannot be reproduced, and an artefact whose bytes change every time
you look at it is hard to talk about. With the date pinned, the same inputs give
the same bytes on the same machine with the same fpdf2 -- which is what makes a
``pdf_hash`` meaningful. It is deliberately *not* promised across fpdf2 versions,
and nothing in this tree ever checks a hash by re-rendering: hashes are taken
over the bytes that were actually received.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import NamedTuple

from fpdf import FPDF

__all__ = ["Rendered", "RenderError", "render", "write_pdf", "FONT_CANDIDATES"]


class RenderError(ValueError):
    """The text cannot be rendered without changing it."""


class Rendered(NamedTuple):
    """A PDF and the facts about how it was made.

    ``font`` is recorded rather than assumed because it changes the bytes: a
    deployment with a Unicode font and one without produce different files from
    the same text, and an artefact that does not say which it is invites a
    comparison that cannot be made.

    ``replaced`` is the number of characters that were swapped for a visible
    replacement character. It is zero in every normal case, and non-zero means
    the file on disk is not a faithful rendering of the text it was made from --
    which a caller holding a marked copy needs to know, because a watermark
    embedded in text that has since changed will not decode.
    """

    data: bytes
    pages: int
    font: str
    replaced: int


# Serif fonts with wide coverage, tried in order. Given as (name, path) so the
# name recorded in the manifest is the one a reader would recognise.
#
# The fallback, when none of these exists, is a PDF core font. That is not a
# merely cosmetic difference: the core fonts are latin-1, so they raise on an em
# dash or a curly quote, which template prose does not contain today and real
# prose always does.
FONT_CANDIDATES = (
    ("LiberationSerif",
     "/usr/share/fonts/liberation-serif-fonts/LiberationSerif-Regular.ttf"),
    ("DejaVuSerif", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("NotoSerif", "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf"),
)

CORE_FONT = "Helvetica"

# The core fonts are latin-1: one byte per character, and nothing above U+00FF.
_CORE_FONT_MAX = 0xFF

# What goes in place of a character the font cannot draw, when the caller has
# accepted substitutions. U+FFFD is the replacement character, which is exactly
# what it means; '?' is the fallback for the unlikely case that even that is
# missing.
_REPLACEMENT = "�"
_REPLACEMENT_FALLBACK = "?"


def _pick_font() -> tuple[str, str | None]:
    for name, path in FONT_CANDIDATES:
        if os.path.exists(path):
            return name, path
    return CORE_FONT, None


def _cmap(font_path: str) -> set[int]:
    """The codepoints the font can actually draw, from its own character map.

    Read with fontTools, which fpdf2 already depends on, rather than inferred
    from fpdf2's behaviour. Asking the font is the only way to know *before*
    rendering: fpdf2 discovers the problem while writing the file and reports it
    through a logger, which is not something a caller can act on.
    """
    from fontTools.ttLib import TTFont

    with TTFont(font_path, lazy=True) as tt:
        return set(tt.getBestCmap())


def _uncovered(text: str, font_path: str | None) -> list[tuple[str, int]]:
    """Characters that would be dropped, in the order they first appear.

    Deduplicated by character, because a report that names the same codepoint
    forty times is a report nobody reads.
    """
    if font_path is None:
        allowed = None
    else:
        try:
            allowed = _cmap(font_path)
        except Exception:
            # A font file that cannot be read is a font we cannot vouch for.
            # Reporting every non-ASCII character as uncovered would be a
            # confusing way to say so; saying so is clearer.
            raise RenderError(f"cannot read the character map of {font_path}")

    seen: dict[str, int] = {}
    for ch in text:
        if ch in seen or ch in "\n\r\t":
            continue
        covered = (ord(ch) <= _CORE_FONT_MAX if allowed is None
                   else ord(ch) in allowed)
        if not covered:
            seen[ch] = ord(ch)
    return list(seen.items())


class _Document(FPDF):
    """Page furniture, applied to every page.

    The classification banner repeats on each page rather than appearing once at
    the top. That is the convention for classified documents, and it is also the
    one that survives the case worth caring about: a single page photographed or
    extracted on its own still says what it is.
    """

    def __init__(self, doc_id: str, classification: str, footer_note: str | None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self._doc_id = doc_id
        self._classification = classification.upper()
        self._footer_note = footer_note

    def header(self) -> None:
        self.set_font(self.font_family, size=9)
        self.set_text_color(140)
        self.cell(0, 5, self._classification, align="C",
                  new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(180)
        y = self.get_y()
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(3)
        self.set_text_color(0)

    def footer(self) -> None:
        # Positioned from the bottom rather than from the current y, because a
        # footer that flows after the body is not a footer.
        self.set_y(-15)
        self.set_font(self.font_family, size=8)
        self.set_text_color(140)
        left = self._doc_id
        if self._footer_note:
            # ASCII hyphen, not an em dash. The furniture drawn here is not part
            # of ``text`` and so is not covered by the caller's glyph check, and
            # a core font would raise on a dash the document body never
            # contained.
            left = f"{left} - {self._footer_note}"
        self.cell(0, 5, left, align="L")
        self.set_y(-15)
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")
        self.set_text_color(0)


def render(text: str, *, doc_id: str, classification: str, created: datetime,
           recipient_id: str | None = None, ledger_index: int | None = None,
           leaf_hash: str | None = None,
           allow_replacements: bool = False) -> Rendered:
    """Render ``text`` to a PDF.

    When ``ledger_index`` and ``leaf_hash`` are given they are printed in the
    footer, which ties a printed page to the ledger entry its mark came from.
    That is a convenience for a human reading the page, and **it is not
    evidence**: the forensic mark is the word substitutions, and a footer is
    something anyone with a text editor can type. It is here because a page that
    names its own provenance is easier to handle correctly than one that does
    not, not because it proves anything.

    Raises :class:`RenderError` if the text cannot be drawn without dropping
    characters, unless ``allow_replacements`` is set.
    """
    if not isinstance(text, str):
        raise RenderError(f"text is {type(text).__name__}, not str")

    font_name, font_path = _pick_font()

    uncovered = _uncovered(text, font_path)
    replaced = len(uncovered)
    if uncovered and not allow_replacements:
        named = ", ".join(f"{ch!r} (U+{cp:04X})" for ch, cp in uncovered[:8])
        more = f" and {replaced - 8} more" if replaced > 8 else ""
        raise RenderError(
            f"{doc_id} contains {replaced} character(s) the font {font_name} "
            f"cannot draw: {named}{more}. Rendering them would drop them, and a "
            "marked copy that has lost characters is a copy whose watermark "
            "will not decode. Pass allow_replacements=True to accept the loss "
            "knowingly.")
    if uncovered:
        # Substituted, not dropped. A visible hole in the page says something
        # was lost; a silently closed gap says the document was always like
        # that, which is the lie worth avoiding.
        swap = _REPLACEMENT
        if _uncovered(_REPLACEMENT, font_path):
            swap = _REPLACEMENT_FALLBACK
        for ch, _ in uncovered:
            text = text.replace(ch, swap)

    note = None
    if ledger_index is not None and leaf_hash:
        # Truncated with three dots rather than an ellipsis character, for the
        # same reason the footer uses a hyphen: this is furniture, and the
        # coverage check above only looked at the body.
        note = f"ledger entry {ledger_index}, leaf {leaf_hash[:16]}..."
    elif recipient_id:
        note = f"issued to {recipient_id}"

    pdf = _Document(doc_id, classification, note)
    if font_path:
        pdf.add_font(font_name, "", font_path)
        pdf.set_font(font_name, size=11)
    else:
        pdf.set_font(font_name, size=11)

    pdf.set_creation_date(created)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.alias_nb_pages()

    try:
        pdf.add_page()

        pdf.set_font_size(14)
        pdf.multi_cell(0, 8, doc_id, align="L")
        pdf.ln(2)
        pdf.set_font_size(11)

        for para in (p.strip() for p in text.split("\n")):
            if not para:
                continue
            pdf.multi_cell(0, 5.5, para, align="J")
            pdf.ln(2)

        raw = pdf.output()
    except RenderError:
        raise
    except Exception as e:
        # A core font raises here for a character outside latin-1, where the
        # TrueType path would have dropped it. Reported as one failure either
        # way, so a caller does not have to know which font it got.
        raise RenderError(f"{doc_id} cannot be rendered: {e}") from e

    return Rendered(data=bytes(raw), pages=pdf.pages_count, font=font_name,
                    replaced=replaced)


def write_pdf(path: str, data: bytes) -> str:
    """Write rendered bytes to disk. The only filesystem write in this module.

    Kept separate and explicit so that nothing renders *and* saves in one step:
    the client node returns bytes and stores nothing, and a caller who wants a
    file on disk says so.
    """
    with open(path, "wb") as fh:
        fh.write(data)
    return path
