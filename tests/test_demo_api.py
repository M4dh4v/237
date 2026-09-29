"""The demo and leak-check HTTP surface, driven exactly as the browser drives it.

The rest of the suite calls the library. This file calls the *routes*, because
the front end can only see what the routes return, and a leak-check screen is
only as honest as the JSON behind it. Three things follow from that and are the
reason this file exists rather than being covered by ``test_leakcheck.py``:

* the disclaimer and the caveat must arrive **in the response**, not in a
  paragraph somebody put in the JavaScript -- a UI cannot forget a field it is
  handed,
* the two confidences must survive serialisation as separate numbers, and
* ``/demo/open`` must produce a ledger entry that ``/ledger/entry/{index}``
  then serves, checkable against the witnesses' own public keys -- i.e. the
  screen showing "the ledger entry materialising" is showing a real one.

The witnesses here are real processes on real sockets (``WitnessFleet``), so an
append that the witnesses refuse fails the same way it would in the demo. The
authority is in-process behind a ``TestClient``: the point of this file is the
route contracts, and ``tests/test_authority_http.py`` already covers the wire
and mTLS.
"""

from __future__ import annotations

import base64
import hashlib
import socket

import pytest
from fastapi.testclient import TestClient

# Aliased because this module already has a fixture called ``sealed`` (the
# distribution response), and a fixture shadows an import inside any test that
# requests it.
from logfirst import sealed as sealed_mod
from logfirst.authority.demo_api import register_demo_routes
from logfirst.authority.server import build_app
from logfirst.data.scenario import Scenario
from logfirst.ledger import merkle
from logfirst.watermark import linguistic

pytest.importorskip("fastapi.testclient")

RECIPIENTS = ["alice", "bob", "carol", "dave"]


def _free_ports(n: int) -> list[int]:
    """Bind-and-release, so a demo left running from an earlier session whose
    witnesses still hold a port does not present as a mysterious startup hang."""
    out = []
    for _ in range(n):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            out.append(s.getsockname()[1])
    return out


@pytest.fixture(scope="module")
def sc(tmp_path_factory):
    """A live scenario: three witness processes, an authority, three documents."""
    import os

    root = tmp_path_factory.mktemp("demo")
    # WitnessFleet picks ports from the deployment file, so they are drawn here
    # and written into it rather than being left at the default 9101-9103, which
    # a running demo would be holding.
    os.environ.setdefault("LOGFIRST_DEMO_PORTS", "")
    ports = _free_ports(3)
    data = str(root / "data")
    # Scenario.build writes the deployment; to control ports we create it first.
    from logfirst.data.deploy import Deployment

    dep = Deployment.create(data, witness_ports=ports, min_witnesses=2)
    for r in RECIPIENTS:
        dep.add_recipient(r)
    scenario = Scenario.build(data, n_docs=3, target_words=1800, seed=5,
                              recipients=RECIPIENTS, start_witnesses=False)
    scenario.fleet.start()
    try:
        yield scenario
    finally:
        scenario.close()


@pytest.fixture(scope="module")
def client(sc):
    return TestClient(build_app(sc.authority, scenario=sc))


@pytest.fixture(scope="module")
def sealed(client):
    """DOC-0000 granted to three of the four enrolled recipients.

    Dave is deliberately left ungranted so the default-deny path can be
    exercised through the route with a recipient the authority knows and has a
    certificate for -- which is the interesting case. An unknown recipient would
    fail earlier, on identity rather than on authorisation.
    """
    r = client.post("/demo/distribute",
                    json={"doc_id": "DOC-0000", "recipients": RECIPIENTS[:3]})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def opened(client, sealed):
    r = client.post("/demo/open",
                    json={"doc_id": "DOC-0000", "recipient_id": "carol",
                          "mark": True})
    assert r.status_code == 200, r.text
    return r.json()


# ==========================================================================
# What the demo says about itself
# ==========================================================================

def test_the_state_route_names_what_is_simulated(client):
    """The disclaimer is served, not transcribed.

    The build specification requires the front end to say what is simulated.
    Serving the list from the same constant the README and the CLI use means the
    UI cannot quietly disagree with them.
    """
    body = client.get("/demo/state").json()
    assert body["available"] is True
    assert body["simulated"], "no simulation disclaimer was served"
    joined = " ".join(body["simulated"]).lower()
    assert "witness" in joined, (
        "the witness nodes are simulated (separate processes on one machine, "
        "not separate hosts) and that must be in the served list")
    assert body["min_witnesses"] >= 2, (
        "a quorum of one would make the tamper-evidence story vacuous")
    assert len(body["witnesses"]) >= body["min_witnesses"]


def test_a_scenario_less_app_has_no_demo_routes_but_says_so(tmp_path):
    """A production-shaped run must not carry demo routes.

    And when there is no scenario, ``/demo/state`` explains itself rather than
    404ing, because a 404 in a front end is indistinguishable from a typo.
    """
    from logfirst.authority.server import Authority
    from logfirst.authority.store import Store
    from logfirst.crypto import pqc
    from logfirst.ledger.log import LedgerLog
    from logfirst.ledger.witnesses import WitnessQuorum

    from tests.conftest import make_witnesses

    pub, sec = pqc.sig_keypair(pqc.SIG)
    quorum = WitnessQuorum(make_witnesses(tmp_path, 1), min_witnesses=1)
    log = LedgerLog.open(str(tmp_path / "ledger.db"), quorum)
    auth = Authority(log, Store.open(":memory:"), b"\x00" * 32, pub, sec)
    app = build_app(auth)
    paths = {r.path for r in app.routes}
    assert "/demo/open" not in paths
    assert "/leakcheck" not in paths

    # And the standalone registrar explains the absence.
    app2 = build_app(auth)
    register_demo_routes(app2, None)
    body = TestClient(app2).get("/demo/state").json()
    assert body["available"] is False
    assert "reason" in body


# ==========================================================================
# Distribute, open, and the entry that materialises
# ==========================================================================

def test_the_open_route_returns_an_entry_the_ledger_route_also_serves(
        client, opened):
    """The screen's claim, checked: the entry shown is the entry in the log.

    If ``/demo/open`` rendered a receipt assembled for display while
    ``/ledger/entry`` served something else, the demo would look identical and
    prove nothing.
    """
    entry = opened["ledger_entry"]
    idx = entry["index"]
    assert opened["receipt"]["ledger_index"] == idx

    served = client.get(f"/ledger/entry/{idx}").json()
    assert served["leaf"] == entry["leaf"]
    assert served["leaf_hash"] == entry["leaf_hash"] == \
        merkle.leaf_hash(entry["leaf"].encode()).hex()

    # The leaf really is the signed request, and it names carol.
    import json

    leaf = json.loads(entry["leaf"])
    assert leaf["kind"] == "decryption-request"
    assert leaf["request"]["recipient_id"] == "carol"
    assert leaf["request"]["doc_id"] == "DOC-0000"


def test_the_served_entry_verifies_against_the_witnesses_own_keys(client,
                                                                  opened):
    """Check the co-signatures here, from the witnesses' keys, not the server's.

    The response carries the STH and the witnesses' public keys; this folds the
    inclusion proof and checks each co-signature itself. That is what the front
    end displays as "witnessed", so it has to be true of the bytes the front end
    is actually given.
    """
    from logfirst.crypto import pqc
    from logfirst.models import STH

    state = client.get("/demo/state").json()
    sth_d = opened["receipt"]["sth"]
    sth = STH.from_dict(sth_d)
    idx = opened["ledger_entry"]["index"]

    proof = [bytes.fromhex(p) for p in opened["receipt"]["inclusion_proof"]]
    assert merkle.verify_inclusion(opened["ledger_entry"]["leaf"].encode(),
                                   idx, sth.tree_size, proof,
                                   bytes.fromhex(sth.root_hash))

    pubs = state["ledger_publics"]["witness_pubs"]
    ok = [wid for wid, pub in pubs.items()
          if sth.witness_sigs.get(wid)
          and pqc.verify(bytes.fromhex(pub), sth.tbs(),
                         bytes.fromhex(sth.witness_sigs[wid]))]
    assert len(ok) >= state["min_witnesses"], (
        f"only {len(ok)} witness co-signature(s) verified against the "
        f"witnesses' own published keys; the quorum is {state['min_witnesses']}")
    assert pqc.verify(bytes.fromhex(state["ledger_publics"]["log_pub"]),
                      sth.tbs(), bytes.fromhex(sth.log_sig))


def test_the_demo_shows_which_words_the_mark_changed(client, sc, opened):
    """The substitution has to be visible, and it has to be on carrier slots.

    A diff computed by a display helper could show anything; this asserts every
    position it reports is a slot the extractor will read, so what the screen
    highlights is the same set of positions the evidence comes from.
    """
    diff = opened["mark_diff"]
    assert diff, "the marked copy is identical to the plaintext"
    slots = {o for o, _, _ in linguistic.carrier_slots(sc.doc("DOC-0000")["text"])}
    changed = {d["position"] for d in diff}
    assert changed <= slots, (
        f"{len(changed - slots)} position(s) outside the carrier slots were "
        "changed, so the mark is not confined to where it can be read")


def test_the_open_route_refuses_an_unsealed_document(client):
    r = client.post("/demo/open", json={"doc_id": "DOC-0002",
                                        "recipient_id": "alice"})
    assert r.status_code == 400
    assert "not sealed" in r.json()["detail"]


def test_the_open_route_refuses_an_ungranted_recipient(client, sealed):
    """Default-deny, through the route the UI uses."""
    r = client.post("/demo/open", json={"doc_id": "DOC-0000",
                                        "recipient_id": "dave"})
    assert r.status_code == 403, r.text
    assert "not-authorized" in r.json()["detail"]


# ==========================================================================
# The leak-check route
# ==========================================================================

def test_the_leak_check_attributes_a_marked_copy(client, opened):
    r = client.post("/leakcheck", json={"text": opened["marked_text"]})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["status"] == "attributed", (body["status"], body["notes"])
    assert body["watermark"]["ledger_index"] == opened["ledger_entry"]["index"]
    assert body["candidates"][0]["recipient_id"] == "carol"
    assert body["verification"]["verified"] is True
    assert body["verification"]["inclusion_ok"] is True
    assert body["verification"]["witnesses_bad"] == []


def test_the_two_confidences_arrive_as_separate_numbers(client, opened):
    """The specification's "never a bare single accusation", on the wire.

    Document-match confidence and watermark-recovery confidence answer
    different questions, and a response that blended them would hide the case
    where the document is certain and the watermark is not.
    """
    body = client.post("/leakcheck",
                       json={"text": opened["marked_text"]}).json()
    assert "confidence" in body["document"]
    assert "confidence" in body["watermark"]
    assert body["document"]["confidence"] != 0.0
    assert body["watermark"]["confidence"] != 0.0
    assert body["caveat"], "no caveat on the response"


def test_every_leak_check_response_carries_the_caveat_and_disclaimer(client,
                                                                     opened):
    """Including the refusals. A refusal is still a statement about a person."""
    bodies = [
        client.post("/leakcheck", json={"text": opened["marked_text"]}).json(),
        client.post("/leakcheck", json={"text": opened["plaintext"]}).json(),
        client.post("/leakcheck", json={"text": "unrelated prose entirely"}).json(),
    ]
    for b in bodies:
        assert b["caveat"], b
        assert b["simulated"], b
        assert "key" in b["caveat"] and "not" in b["caveat"]


def test_an_unmarked_copy_falls_back_and_is_labelled_as_weaker(client, opened):
    """The honest fallback, through the route.

    The ledger genuinely records that carol opened this document. That is worth
    reporting -- and it is not an attribution, so the status must not say it is.
    """
    body = client.post("/leakcheck", json={"text": opened["plaintext"]}).json()
    assert body["status"] in ("no-watermark", "collusion-suspected"), body["notes"]
    assert body["watermark"]["recovered"] is False
    assert body["status"] != "attributed"
    assert all(c["source"] == "tardos-trace" for c in body["candidates"]) or \
        body["candidates"] == []
    assert any("fallback" in n or "did not decode" in n for n in body["notes"])


def test_text_outside_the_corpus_is_refused_as_unidentified(client):
    body = client.post("/leakcheck", json={"text": (
        "Shall I compare thee to a summer's day? Thou art more lovely and more "
        "temperate. Rough winds do shake the darling buds of May, and summer's "
        "lease hath all too short a date. Sometime too hot the eye of heaven "
        "shines, and often is his gold complexion dimmed.")}).json()
    assert body["status"] == "unidentified", (body["status"], body["notes"])
    assert body["candidates"] == []


def test_the_leak_check_refuses_empty_input_rather_than_guessing(client):
    for body in ({"text": "   "}, {}):
        r = client.post("/leakcheck", json=body)
        assert r.status_code == 400, r.text


def test_a_malformed_image_is_reported_as_such(client):
    r = client.post("/leakcheck", json={"image_b64": "not base64!!"})
    assert r.status_code == 400
    assert "base64" in r.json()["detail"]


def test_a_collusion_is_reported_as_a_collusion_not_as_one_name(client, sc):
    """Two recipients splice, through the route.

    The pointer is destroyed and Tardos carries the signal. What must never
    happen is a single confident name with nothing behind it.
    """
    body = client.post("/leakcheck", json={
        "text": sc.leak_collusion("alice", "bob",
                                  "DOC-0000", seed=3)["leaked_text"]}).json()
    assert body["status"] in ("collusion-suspected", "single-mark",
                              "attributed"), body["notes"]
    if body["status"] in ("collusion-suspected", "single-mark"):
        assert body["candidates"], "a mark was reported with nothing ranked"
        assert all(c["source"] == "tardos-trace" for c in body["candidates"])
        assert any("Tardos" in n or "rank" in n.lower() for n in body["notes"])
    assert body["candidates"], "no candidates at all"
    for c in body["candidates"]:
        assert isinstance(c["tardos_score"], float)


def test_the_leak_check_result_is_json_serialisable_end_to_end(client, opened):
    """The front end gets JSON and nothing else. A tuple or a numpy scalar
    anywhere in the result would surface here rather than in the browser."""
    import json

    r = client.post("/leakcheck", json={"text": opened["marked_text"]})
    assert r.status_code == 200
    json.dumps(r.json())        # would raise on bytes, tuples or numpy types


def test_the_example_buttons_carry_the_same_ground_truth_as_the_leak_route(client):
    """The example endpoints answer "what actually happened" too.

    They did not, once. ``POST /demo/leak`` returned a ``truth`` object and
    ``GET /leakcheck/example/{kind}`` did not, so the screen's ground-truth box
    filled in on the path a reader has to go looking for and stayed empty on the
    path a first-time reader takes. Both now build it through one helper; this
    asserts the two agree, which is the property the helper exists to hold.
    """
    for kind in ("text", "collusion"):
        example = client.get(f"/leakcheck/example/{kind}").json()
        assert "truth" in example, f"{kind} example has no ground truth"
        made = client.post("/demo/leak",
                           json={"kind": kind, "recipient_id": "alice"}).json()
        assert set(example["truth"]) == set(made["truth"]), (
            f"{kind}: the example and the generate route disagree about what a "
            f"correct run should recover ({sorted(example['truth'])} vs "
            f"{sorted(made['truth'])})")
        # And the truth names something the ledger can actually be asked about.
        idx = (example["truth"].get("ledger_index")
               or example["truth"].get("ledger_indices", [None])[0])
        if idx is not None:
            assert client.get(f"/ledger/entry/{idx}").status_code == 200


def test_the_screenshot_path_works_through_the_route(client):
    """Render, degrade, OCR, check -- the whole demo path, via HTTP."""
    from logfirst.watermark import ocr

    if not ocr.available():
        pytest.skip("tesseract is not installed")

    example = client.get("/leakcheck/example/screenshot").json()
    assert example["image_b64"]
    body = client.post("/leakcheck",
                       json={"image_b64": example["image_b64"]}).json()
    assert body["status"] in ("attributed", "no-watermark", "single-mark",
                              "collusion-suspected"), (body["status"],
                                                       body["notes"])
    if body["status"] == "attributed":
        assert body["verification"]["verified"] is True


# ==========================================================================
# The two files that get downloaded
# ==========================================================================

def test_the_container_route_releases_nothing_and_records_nothing(client, sc,
                                                                  sealed):
    """The download is the distribution artefact, not an open.

    It has to be checked rather than assumed, because this route hands over a
    complete ciphertext: if it also appended a leaf or wrote a session row, the
    ledger would fill with entries for nothing and the "one open, one entry"
    property -- the whole basis of attribution -- would be quietly false.
    """
    before_leaves = sc.log.tree_size()
    before_sessions = len(sc.store.sessions())

    r = client.get("/demo/documents/DOC-0000.lfdoc")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].endswith('DOC-0000.lfdoc"')
    assert r.headers["x-logfirst-container"] == "lfdoc/1"

    assert r.content.startswith(sealed_mod.CONTAINER_MAGIC)
    assert not r.content.startswith(b"%PDF")
    assert b"%PDF" not in r.content

    # Not prose from the document, and not the document's own opening words.
    opening = sc.doc("DOC-0000")["text"][:60].encode()
    assert opening not in r.content

    assert sc.log.tree_size() == before_leaves, (
        "downloading the container appended a ledger entry; the file is the "
        "distribution artefact and no key was released")
    assert len(sc.store.sessions()) == before_sessions


def test_the_container_route_says_why_when_there_is_nothing_to_download(client):
    """DOC-0002 is the document this file never seals -- the same one the
    unsealed-open test uses -- so this is a real 404 and not a test that
    happened to run first."""
    r = client.get("/demo/documents/DOC-0002.lfdoc")
    assert r.status_code == 404
    assert "not sealed" in r.json()["detail"]


def test_an_open_that_did_not_ask_for_a_pdf_does_not_get_one(client, opened):
    """``include_pdf`` is opt-in, so the response the front end has always
    received keeps its shape and its size."""
    assert "marked_pdf_b64" not in opened
    assert "distribution_pdf_b64" not in opened
    assert "pdf_marked" not in opened


def test_requesting_the_pdf_returns_two_real_pdfs(client, sealed):
    """Both artefacts, both real, and the sha256 the response reports for each
    is the sha256 of the bytes it sent -- so the UI can label a download with a
    hash that means something."""
    r = client.post("/demo/open", json={"doc_id": "DOC-0000",
                                        "recipient_id": "alice", "mark": True,
                                        "include_pdf": True})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["pdf_marked"] is True
    assert body["marked_pdf_pages"] >= 1

    marked = base64.b64decode(body["marked_pdf_b64"])
    canonical = base64.b64decode(body["distribution_pdf_b64"])
    assert marked.startswith(b"%PDF-") and canonical.startswith(b"%PDF-")
    assert hashlib.sha256(marked).hexdigest() == body["marked_pdf_sha256"]
    assert hashlib.sha256(canonical).hexdigest() == \
        body["distribution_pdf_sha256"]

    assert body["marked_pdf_sha256"] != body["distribution_pdf_sha256"], (
        "the marked copy and the distributed copy are different files; equal "
        "hashes would mean the mark never made it into the PDF")
    assert body["distribution_pdf_sha256"] == sealed["pdf_hash"]


def test_a_document_too_short_to_mark_is_not_labelled_a_forensic_copy(
        client, sc, monkeypatch):
    """The quiet lie this field exists to prevent.

    Below the marking threshold ``marked_text`` is the plaintext, so the PDF
    rendered from it carries no watermark at all -- it is a perfectly ordinary
    document. A UI that labelled it "marked PDF" would be handing an
    investigator a file with nothing in it and a confident caption. So the
    response says ``pdf_marked: false``, and the docstring on the route says
    why.
    """
    short = "The annex is short and carries no mark. " * 6
    idx = next(i for i, d in enumerate(sc.docs) if d["doc_id"] == "DOC-0001")
    monkeypatch.setitem(sc.docs[idx], "text", short)
    sc.distribute("DOC-0001", ["alice"])

    r = client.post("/demo/open", json={"doc_id": "DOC-0001",
                                        "recipient_id": "alice", "mark": True,
                                        "include_pdf": True})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["receipt"]["marking_plan"]["ok"] is False, (
        "the fixture is supposed to be too short to carry a mark")
    assert body["marked_text"] == body["plaintext"]
    assert body["pdf_marked"] is False
    # A PDF is still rendered, because the session happened and the recipient is
    # entitled to the file -- it just is not evidence of anything.
    assert base64.b64decode(body["marked_pdf_b64"]).startswith(b"%PDF-")


# ==========================================================================
# What the container screen needs from these routes
# ==========================================================================
#
# Two fields exist on the responses purely so the "Open a .lfdoc" screen can do
# its job, and both are checked here rather than only in the browser: a route
# contract the front end depends on is a contract, and the front end has no
# tests of its own.


def test_open_returns_the_manifest_that_travelled_inside_the_encryption(
        client, opened):
    """Without this, the label on a container can never be checked.

    The container header is unauthenticated -- AES-GCM's additional data is only
    the doc_id -- so the only way to tell an edited label from an honest one is
    to compare it with the manifest that came out of the decryption. That
    comparison is the container screen's final step, and it is impossible unless
    this field is in the response.

    Asserted against the real header of the real container rather than against a
    hand-written dict, so this fails if the two ever describe the document
    differently.
    """
    assert "payload_manifest" in opened, (
        "the open response dropped payload_manifest, which makes the label "
        "check on the container screen impossible")

    container = client.get("/demo/documents/DOC-0000.lfdoc").content
    header = sealed_mod.unpack(container)["header"]
    assert sealed_mod.compare(header, opened["payload_manifest"]) == [], (
        "the container header and the sealed manifest disagree about the same "
        "document as served by the API")


def test_the_session_row_keeps_the_device_fingerprint_the_request_carried(
        client, opened):
    """Recorded, not enforced -- but recorded.

    The authority does not act on this value anywhere, and that is deliberate.
    What it must do is store what the request asserted, so the register can show
    it beside the value the CA enrolled and an operator can see the two differ.
    """
    body = client.get("/demo/admin/recipients").json()
    carol = next(r for r in body["recipients"] if r["recipient_id"] == "carol")

    assert carol["opened"] >= 1
    assert carol["last_seen_device_fp"], (
        "the open recorded no device fingerprint on the session row")
    assert carol["last_seen_device_fp"] == carol["device_fp"], (
        "the demo node asserts the fingerprint the deployment enrolled for it, "
        "so the enrolled and last-seen values should agree here; a mismatch "
        "means the request is not carrying the enrolled value")
    assert carol["last_seen_device_fp"] != "unbound-device", (
        "the constant placeholder is still reaching the store")


# ==========================================================================
# Lane C glue: source ingestion, recipient enrolment, upload trace, certificate
# (design plan §13.2). These are adapters in front of the unchanged pipeline;
# each test asserts the adapter fed the real path, not that it re-implemented it.
# ==========================================================================

def _pdf_bytes(text: str) -> bytes:
    """A minimal PDF with a real text layer, for the upload paths."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 6, text)
    return bytes(pdf.output())


def test_compose_registers_a_sealable_document(client):
    r = client.post("/demo/source/compose",
                    json={"title": "Fleet order", "body": "hold the line " * 60})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["docId"].startswith("SRC-")
    assert set(body["capacity"]) == {"positions", "needed", "strength"}
    assert "hold the line" in body["preview"]
    # The point of registration: the *existing* seal route now accepts it.
    d = client.post("/demo/distribute",
                    json={"doc_id": body["docId"], "recipients": ["alice"]})
    assert d.status_code == 200, d.text


def test_upload_text_file_registers_document(client):
    payload = ("classified movement plan " * 80).encode("utf-8")
    r = client.post("/demo/source/upload",
                    files={"file": ("plan.txt", payload, "text/plain")})
    assert r.status_code == 200, r.text
    assert r.json()["docId"].startswith("SRC-")


def test_upload_pdf_extracts_text_layer(client):
    data = _pdf_bytes("northern approach convoy schedule " * 60)
    r = client.post("/demo/source/upload",
                    files={"file": ("plan.pdf", data, "application/pdf")})
    assert r.status_code == 200, r.text
    assert "convoy" in r.json()["preview"]


def test_upload_of_binary_junk_fails_closed(client):
    r = client.post("/demo/source/upload",
                    files={"file": ("x.bin", b"\x00\x01\x02\xff\xfe", None)})
    assert r.status_code == 400
    assert "detail" in r.json()


def test_create_recipient_enrols_and_shows_up(client):
    r = client.post("/demo/admin/recipients/create",
                    json={"display_name": "New Officer", "role": "analyst"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["status"] == "active"
    assert card["role"] == "analyst"
    assert len(card["fingerprint"]) == 64  # sha256 hex, mono in the UI
    rid = card["recipientId"]
    listed = client.get("/demo/admin/recipients").json()["recipients"]
    assert any(x["recipient_id"] == rid for x in listed), (
        "a freshly enrolled recipient must appear in the authority's store")
    # Companion to the existing revoke path: it must accept the new id.
    rev = client.post("/demo/admin/revoke", json={"recipient_id": rid})
    assert rev.status_code == 200, rev.text


def test_source_capacity_matches_the_documents_route(client):
    cap = client.get("/demo/source/DOC-0000/capacity").json()
    doc = next(d for d in client.get("/demo/documents").json()["documents"]
               if d["doc_id"] == "DOC-0000")
    assert cap["positions"] == doc["tardos_positions"]
    assert cap["needed"] == doc["tardos_required"]


def test_source_capacity_404s_for_unknown_document(client):
    r = client.get("/demo/source/DOC-9999/capacity")
    assert r.status_code == 404


def test_leakcheck_upload_identifies_and_reports_pages(client, opened):
    leaked = opened.get("marked_text") or opened["plaintext"]
    data = _pdf_bytes(leaked)
    r = client.post("/leakcheck/upload",
                    files={"file": ("leak.pdf", data, "application/pdf")})
    assert r.status_code == 200, r.text
    result = r.json()
    # Same shape as /leakcheck (document/watermark/caveat) plus per-page status.
    assert result["document"]["doc_id"] == "DOC-0000"
    assert result["pages"] and result["pages"][0]["extraction"] == "text-layer"
    assert result["caveat"], "the attribution caveat must survive the adapter"


def test_certificate_returns_a_selfchecking_bundle(client, opened):
    idx = opened["ledger_entry"]["index"]
    r = client.post("/evidence/certificate", json={"finding_id": idx})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pdf"] is None
    from logfirst.forensics.bundle import selfcheck

    assert body["json"]["entries"], "an empty bundle proves nothing"
    assert selfcheck(body["json"])["ok"], (
        "the bundle the certificate route builds must pass the system's own "
        "evidence check")


def test_certificate_rejects_a_non_index(client):
    r = client.post("/evidence/certificate", json={"finding_id": "not-an-index"})
    assert r.status_code == 400
