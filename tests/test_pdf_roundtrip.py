"""The claim the whole feature exists for, exercised through real files.

``test_sealed.py`` shows the container is locked. ``test_pdfdoc.py`` shows the
renderer produces a real PDF. Neither of them shows the thing a person actually
cares about, which is this:

    the file you downloaded is the file the server decrypted, and the file you
    get back after opening it still names you when it leaks.

That second half is the one worth being careful about, so it is not tested by
re-implementing the pipeline. A marked PDF is rendered, written to disk,
**read back with poppler** -- the same tool a leak investigator would point at a
screenshot or a scanned page -- and fed to the real :class:`Investigator`. If
the mark does not survive that, it does not survive anything, and the honest
finding would be that the system attributes nothing but its own in-memory
strings.

The last two tests are about ordering rather than artefacts: the key release
happens *before* anything is rendered (so a renderer that dies cannot sit
between the ledger append and the key), and a dead quorum produces no key and
no file at all.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import socket
import subprocess

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("oqs")
pytest.importorskip("fpdf")

from logfirst import pdfdoc, sealed                                    # noqa: E402
from logfirst.authority.server import build_app                        # noqa: E402
from logfirst.client.node import OpenRefused                           # noqa: E402
from logfirst.data.deploy import Deployment                            # noqa: E402
from logfirst.data.scenario import Scenario                            # noqa: E402
from logfirst.forensics import align                                   # noqa: E402

RECIPIENTS = ["alice", "bob", "carol", "dave"]

requires_poppler = pytest.mark.skipif(
    shutil.which("pdftotext") is None,
    reason="pdftotext is not installed, so a PDF cannot be read back as text; "
           "these are the tests that check the mark survives the file format")


def _free_ports(n: int) -> list[int]:
    """Bind-and-release. The default witness ports are fixed, so a demo left
    running from an earlier session would otherwise present as a startup hang."""
    out = []
    for _ in range(n):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            out.append(s.getsockname()[1])
    return out


def _pdf_text(data: bytes, tmp_path) -> str:
    """A PDF, out of a file, back as text -- the way an investigator meets one."""
    path = tmp_path / "copy.pdf"
    path.write_bytes(data)
    out = subprocess.run(["pdftotext", str(path), "-"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.fixture(scope="module")
def sc(tmp_path_factory):
    root = tmp_path_factory.mktemp("roundtrip")
    data = str(root / "data")
    dep = Deployment.create(data, witness_ports=_free_ports(3), min_witnesses=2)
    for r in RECIPIENTS:
        dep.add_recipient(r)
    scenario = Scenario.build(data, n_docs=3, target_words=2200, seed=11,
                              recipients=RECIPIENTS, start_witnesses=False)
    scenario.fleet.start()
    try:
        yield scenario
    finally:
        scenario.close()


@pytest.fixture(scope="module")
def sealed_doc(sc):
    return sc.distribute("DOC-0000", RECIPIENTS[:3])


@pytest.fixture(scope="module")
def client(sc):
    return TestClient(build_app(sc.authority, scenario=sc))


@pytest.fixture(scope="module")
def investigator(sc):
    """Built once: constructing it generates the Tardos code at the formal
    length, which is real work and has nothing to do with what is under test."""
    return sc.investigator()


@pytest.fixture(scope="module")
def opened(sc, sealed_doc):
    """One real open, through the client node, with the mark embedded."""
    return sc.node("carol").open("DOC-0000", mark=True)


# ==========================================================================
# The distribution artefact is the document, and it is the same document
# ==========================================================================

def test_the_pdf_that_comes_out_is_the_pdf_that_went_in(sc, sealed_doc, opened):
    """``distribution_pdf`` is recovered from inside the AEAD, so this is really
    checking that the frame survived: the bytes coming out are the bytes that
    went in, and they hash to the value the manifest recorded at seal time."""
    assert opened["distribution_pdf"].startswith(b"%PDF-")
    assert hashlib.sha256(opened["distribution_pdf"]).hexdigest() == \
        sealed_doc["pdf_hash"]
    assert opened["payload_manifest"]["pdf_hash"] == sealed_doc["pdf_hash"]
    assert opened["payload_manifest"]["pages"] == sealed_doc["pages"]


@requires_poppler
def test_the_distributed_pdf_carries_the_canonical_text(sc, opened, tmp_path):
    """The sealed copy is the *unmarked* one. That is not an oversight: the mark
    is derived from the leaf hash of an open, and at distribution no open has
    happened, so there is nothing to derive it from yet.

    The banner and the footer are in the extracted text too, which is why this
    aligns rather than comparing a prefix: the furniture is *supposed* to be
    there on every page, and a test that tripped over it would be measuring the
    wrong thing.
    """
    text = _pdf_text(opened["distribution_pdf"], tmp_path)
    canonical = sc.doc("DOC-0000")["text"]
    mapping = align.align(canonical, text)
    assert align.coverage(canonical, mapping) > 0.95

    # And the words are the canonical ones: this copy carries no mark, because
    # there was no ledger entry to derive one from at distribution time.
    canon = align.tokens(canonical)
    same = sum(1 for i, w in mapping.items() if w == canon[i])
    assert same / len(mapping) > 0.98, (
        "the distributed copy differs from the canonical text in "
        f"{len(mapping) - same} places, so it is not the unmarked document")


def test_the_artefact_is_per_document_and_the_mark_is_per_session(sc, opened):
    """Two opens of one document. The distributed PDF is identical both times --
    it is a property of the document. The marked text is not, because it is a
    property of the *session*, which is what makes a leaked copy name one open
    rather than a recipient in general."""
    second = sc.node("carol").open("DOC-0000", mark=True)

    assert second["distribution_pdf"] == opened["distribution_pdf"]
    assert second["ledger_index"] != opened["ledger_index"]
    assert second["marked_text"] != opened["marked_text"]
    assert second["watermark_seed"] != opened["watermark_seed"]

    # And both are still the same document underneath the mark.
    assert len(align.tokens(second["marked_text"])) == \
        len(align.tokens(opened["marked_text"]))


def test_marking_does_not_change_the_word_count(sc, opened):
    """Substitution only, never insertion. A mark that added or removed words
    would be detectable by counting, which is a cheap way to find the watermark
    and strip it."""
    assert opened["marking_plan"]["ok"] is True
    canonical = sc.doc("DOC-0000")["text"]
    assert len(align.tokens(opened["marked_text"])) == \
        len(align.tokens(canonical))
    assert align.coverage(canonical,
                          align.align(canonical, opened["marked_text"])) > 0.95


# ==========================================================================
# The trace survives a real PDF pass
# ==========================================================================

@requires_poppler
def test_the_mark_survives_being_printed_to_pdf_and_read_back(client, sc,
                                                              investigator,
                                                              tmp_path):
    """The end-to-end claim, with a real PDF tool in the middle.

    The copy goes: marked text -> this project's renderer -> a file on disk ->
    poppler -> the investigator. Nothing in that chain is told what to look for,
    and the answer it gives back is the ledger index of the open that produced
    *this* copy. That is attribution: not "this came from alice" but "this came
    from one specific open, and here is the entry".
    """
    r = client.post("/demo/open", json={"doc_id": "DOC-0000",
                                        "recipient_id": "alice", "mark": True,
                                        "include_pdf": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pdf_marked"] is True, body.get("receipt")

    idx = body["receipt"]["ledger_index"]
    marked_pdf = base64.b64decode(body["marked_pdf_b64"])
    assert marked_pdf.startswith(b"%PDF-")
    assert hashlib.sha256(marked_pdf).hexdigest() == body["marked_pdf_sha256"]
    assert body["marked_pdf_sha256"] != body["distribution_pdf_sha256"], (
        "the marked copy must not be the file that was distributed; if the two "
        "hashes matched there would be no mark in it at all")

    leaked = _pdf_text(marked_pdf, tmp_path)
    assert "alice" not in leaked, (
        "the footer names the ledger entry, not the recipient: a copy that "
        "carried its owner's name would be attributable by reading it, and the "
        "whole point is that it is not")

    result = investigator.investigate(leaked_text=leaked)
    assert result.watermark_recovered is True, result.notes
    assert result.pointer_index == idx
    assert result.doc_id == "DOC-0000"


@requires_poppler
def test_the_canonical_pdf_does_not_attribute_anyone(client, sc, investigator,
                                                     tmp_path):
    """The negative half, and the reason the marked copy has to be produced per
    session rather than shipped at distribution: the file everyone downloads is
    genuinely unattributable, and saying so is the difference between a
    watermark and a claim about one."""
    sc.distribute("DOC-0001", ["bob"])
    r = client.post("/demo/open", json={"doc_id": "DOC-0001",
                                        "recipient_id": "bob", "mark": True,
                                        "include_pdf": True})
    assert r.status_code == 200, r.text
    canonical = base64.b64decode(r.json()["distribution_pdf_b64"])

    result = investigator.investigate(
        leaked_text=_pdf_text(canonical, tmp_path))
    assert result.watermark_recovered is False


# ==========================================================================
# Ordering: nothing renders before the key is released
# ==========================================================================

def test_a_renderer_that_dies_after_a_successful_open_leaves_the_entry(client,
                                                                       sc,
                                                                       monkeypatch):
    """The open genuinely happened, so the ledger says so -- and the caller is
    told the PDF failed rather than handed an unmarked one.

    This is the ordering the plan calls load-bearing: rendering runs strictly
    after :meth:`ClientNode.open` returns, so a rendering failure can never sit
    between the ledger append and the key release. The test asserts both ends:
    a 5xx to the caller, and an entry that is really on the ledger afterwards.
    """
    before = sc.log.tree_size()

    def boom(*a, **kw):
        raise pdfdoc.RenderError("the renderer is broken, on purpose")

    monkeypatch.setattr(pdfdoc, "render", boom)
    loud = TestClient(build_app(sc.authority, scenario=sc),
                      raise_server_exceptions=False)
    r = loud.post("/demo/open", json={"doc_id": "DOC-0000",
                                      "recipient_id": "bob", "mark": True,
                                      "include_pdf": True})
    assert r.status_code >= 500, r.text
    assert "marked_pdf_b64" not in r.text
    assert sc.log.tree_size() == before + 1, (
        "the open returned before rendering began, so the entry is real: the "
        "key was released and the ledger says so, and the failed rendering is "
        "reported rather than being allowed to look like a refused open")

    # And the entry it left is a real one, not a placeholder.
    entry = client.get(f"/ledger/entry/{before}").json()
    assert entry["index"] == before


def test_a_dead_quorum_means_no_key_and_no_pdf(tmp_path):
    """Fail-closed, on a deployment whose witnesses were never started.

    No ledger entry, no key release, and therefore no marked PDF -- because the
    mark is derived from the leaf hash of the entry that could not be written.
    There is no degraded mode in which a document opens without one.
    """
    data = str(tmp_path / "dark")
    dep = Deployment.create(data, witness_ports=_free_ports(3), min_witnesses=2)
    dep.add_recipient("alice")
    with Scenario.build(data, n_docs=1, target_words=2200, seed=3,
                        recipients=["alice"], start_witnesses=False) as dark:
        dark.authority.seal(dark.doc("DOC-0000")["text"], "DOC-0000", "SECRET",
                            ["alice"])
        before = dark.log.tree_size()

        with pytest.raises(OpenRefused) as e:
            dark.node("alice").open("DOC-0000", mark=True)
        assert e.value.status in (0, 503)

        assert dark.log.tree_size() == before, (
            "an entry was appended even though a quorum never signed it")


# ==========================================================================
# The container on the wire is the container on disk
# ==========================================================================

def test_what_the_browser_downloads_is_what_the_authority_decrypts(client, sc,
                                                                   monkeypatch):
    """The one comparison that decides whether the download is an artefact or a
    decoration.

    The container is fetched over HTTP at distribution time. The open travels a
    completely different path -- a signed request, answered from the store's own
    copy of the ciphertext. This test does not assume those two are the same
    bytes; it records what the authority actually handed over during a real open
    and holds the downloaded file against it. If they differed, the file on disk
    would be a souvenir.
    """
    r = client.get("/demo/documents/DOC-0000.lfdoc")
    assert r.status_code == 200
    container = sealed.unpack(r.content)

    released: dict = {}
    real_open = sc.authority.open_document

    def recording(dr, **kw):
        receipt = real_open(dr, **kw)
        released[dr.recipient_id] = receipt
        return receipt

    monkeypatch.setattr(sc.authority, "open_document", recording)
    opened = client.post("/demo/open", json={"doc_id": "DOC-0000",
                                             "recipient_id": "carol",
                                             "mark": False})
    assert opened.status_code == 200, opened.text

    handed_over = released["carol"]
    assert container["ciphertext"].hex() == handed_over["ciphertext"]
    assert container["header"]["nonce"] == handed_over["nonce"]
    assert container["header"]["doc_id"] == handed_over["doc_id"]


def test_the_header_describes_the_file_that_is_actually_inside_it(client, sc):
    """The header is a label, and a label that disagrees with the file it is
    pasted on is worse than no label -- so its checkable claims are checked, by
    hashing the artefact a real open hands back."""
    header = sealed.describe(client.get("/demo/documents/DOC-0000.lfdoc").content)
    pdf = base64.b64decode(client.post(
        "/demo/open", json={"doc_id": "DOC-0000", "recipient_id": "alice",
                            "mark": False, "include_pdf": True}).json()
        ["distribution_pdf_b64"])

    assert header["pdf_hash"] == hashlib.sha256(pdf).hexdigest()
    assert header["doc_hash"] == sc.store.get_document("DOC-0000")["doc_hash"]
    assert isinstance(header["pages"], int) and header["pages"] >= 1


def test_an_unsealed_document_has_nothing_to_download(client, sc):
    """A 404 with a reason, rather than an empty file the browser saves under a
    name that suggests it is the document.

    DOC-0002 is the one document in this scenario nobody ever distributes, so
    this is a real "not sealed yet" rather than a document some earlier test
    happened to seal first.
    """
    missing = client.get("/demo/documents/DOC-0002.lfdoc")
    assert missing.status_code == 404

    sc.distribute("DOC-0002", ["alice"])
    now = client.get("/demo/documents/DOC-0002.lfdoc")
    assert now.status_code == 200
    assert sealed.unpack(now.content)["header"]["doc_id"] == "DOC-0002"

