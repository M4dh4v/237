"""The whole system over real sockets, with real witness processes.

Everything else in the suite replaces the witnesses with an in-process stand-in,
which is the right trade for testing quorum arithmetic -- but it leaves one gap
that no amount of unit testing closes: whether the pieces actually talk to each
other. A JSON field renamed on one side, a 409 that arrives as a 500, a witness
that cannot load its own state file, a timestamp that serialises differently
over the wire than in memory, a SQLite handle used from the wrong thread -- all
of those pass every in-process test and fail the moment a socket and a second
process are involved.

So this file stands up the system the way the demo does, with nothing stubbed:

* three witness nodes as **separate OS processes** on their own ports;
* the authority as **its own process under uvicorn**, reached over HTTP with the
  real ``ClientNode`` making real requests;
* a real :class:`Deployment` on disk, with CA-issued certificates.

The authority is a separate process rather than an in-process ``TestClient``
deliberately. uvicorn runs synchronous endpoints on a worker thread, so this is
the only arrangement in which the ledger's and store's ``check_same_thread=False``
handling is genuinely exercised; an in-process test client shares the object
across a thread boundary in a way that can hide the difference. It also means
observations here go through the same HTTP surface a real client uses, or
through a fresh SQLite handle -- never through the server's live objects, which
would be reading a cache rather than the committed state.

Two honest notes about what this does and does not demonstrate.

* The witnesses are separate *processes on one host*, not separate machines.
  That is enough to show the authority cannot produce a co-signature without
  asking -- which is the property the fail-closed path depends on -- but they
  share a kernel, a filesystem and an administrator. A production deployment
  needs them on separate hosts; README says so.
* The authority is served with ``--no-tls`` here. The request signature is what
  this file is testing, and mTLS is orthogonal to it -- but the authority still
  demands a valid ML-DSA signature over every request body, so nothing below is
  authenticated merely by the absence of TLS. That TLS material is genuinely
  issued is checked separately, at the end.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
pytest.importorskip("oqs")

from logfirst.authority.server import ATTRIBUTION_CAVEAT      # noqa: E402
from logfirst.authority.store import Store                     # noqa: E402
from logfirst.client.node import ClientNode                    # noqa: E402
from logfirst.crypto import onetime, pqc                       # noqa: E402
from logfirst.crypto.ca import decrypt_document                # noqa: E402
from logfirst.data.deploy import Deployment, WitnessFleet      # noqa: E402
from logfirst.ledger import merkle                             # noqa: E402
from logfirst.models import STH, DecryptionRequest             # noqa: E402
from logfirst import proc as proc_mod                          # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOC = "DOC-0001"
UNGRANTED = "DOC-UNGRANTED"
TEXT = ("The quarterly assessment records that the northern corridor remains "
        "the primary route for materiel movement, and that resupply intervals "
        "have shortened since the previous reporting period.")


def _free_port() -> int:
    """A port nothing is listening on right now.

    Bound and released rather than drawn from a fixed range, so the suite does
    not collide with a demo left running from an earlier session -- which, given
    ``WitnessFleet._check_ports_free`` deliberately refuses to start over a live
    witness, would otherwise present as a confusing startup failure.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(port: int, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health",
                         timeout=0.5).status_code == 200:
                return
        except Exception as e:      # not up yet
            last = e
            time.sleep(0.15)
    raise AssertionError(f"authority on port {port} never came up: {last}")


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """Three witness processes, a uvicorn authority, and a sealed document."""
    root = tmp_path_factory.mktemp("live")
    ports = [_free_port() for _ in range(3)]
    auth_port = _free_port()

    dep = Deployment.create(str(root / "data"), witness_ports=ports,
                            min_witnesses=2)
    for rid in ("alice", "bob", "carol"):
        dep.add_recipient(rid)

    # Populate the authority's store from the CA's issued certificates, then
    # close our handle: from here the server process owns that database and
    # everything this file observes goes through HTTP or a fresh read-only
    # connection.
    # The same filename the authority's own entry point uses (server.main):
    # ``{data}/store.db``, with the ledger beside it as ``{data}/ledger.db``.
    store = Store.open(dep.path("store.db"), check_same_thread=False)
    dep.sync_store(store)
    store.conn.close()

    env = {**os.environ}
    oqs_lib = "/home/madhav/_oqs/lib64"
    env["LD_LIBRARY_PATH"] = oqs_lib + (
        ":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")

    fleet = WitnessFleet(dep)
    fleet.start()
    proc = proc_mod.Popen(
        [sys.executable, "-m", "logfirst.authority.server",
         "--data", dep.data_dir, "--port", str(auth_port), "--no-tls",
         "--witness-ports", ",".join(str(p) for p in ports),
         "--min-witnesses", "2"],
        cwd=str(REPO), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        _wait_http(auth_port)
        base = f"http://127.0.0.1:{auth_port}"
        with httpx.Client(base_url=base, timeout=30.0) as c:
            for doc_id, recipients in ((DOC, ["alice", "bob", "carol"]),
                                       (UNGRANTED, [])):
                r = c.post("/documents", json={"doc_id": doc_id,
                                               "classification": "SECRET",
                                               "text": TEXT,
                                               "recipients": recipients})
                assert r.status_code == 200, r.text
        yield {"dep": dep, "fleet": fleet, "ports": ports, "base": base,
               "auth_port": auth_port, "proc": proc}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        fleet.stop()
        if proc.stdout:
            proc.stdout.close()


# --------------------------------------------------------------------------
# Observation helpers: HTTP, or a fresh handle -- never the server's objects
# --------------------------------------------------------------------------

@pytest.fixture
def api(live):
    with httpx.Client(base_url=live["base"], timeout=30.0) as c:
        yield c


def _head(live) -> dict:
    return httpx.get(f"{live['base']}/ledger/head", timeout=15.0).json()


def _entry(live, index: int) -> dict:
    return httpx.get(f"{live['base']}/ledger/entry/{index}", timeout=15.0).json()


def _size(live) -> int:
    return _head(live)["tree_size"]


def _sessions(live) -> list[dict]:
    """Read the session table directly, on a connection opened just now.

    Deliberately not through the server's ``Store`` object: that object is in
    another process here, and even in-process its rows would be cached. The
    claim under test is about what is on disk.
    """
    conn = sqlite3.connect(f"file:{live['dep'].path('store.db')}?mode=ro",
                           uri=True)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM sessions")]
    finally:
        conn.close()


def _set_revoked(live, rid: str, revoked: bool) -> None:
    conn = sqlite3.connect(live["dep"].path("store.db"))
    try:
        conn.execute("UPDATE recipients SET revoked=? WHERE recipient_id=?",
                     (int(revoked), rid))
        conn.commit()
    finally:
        conn.close()


def _node(live, rid: str, **kw) -> ClientNode:
    dep = live["dep"]
    return ClientNode(rid, dep.cert_for(rid),
                      bytes.fromhex(dep.secrets_for(rid)["sig_sec"]),
                      authority_url=live["base"], device_fp="dev-" + rid, **kw)


def _open_over_http(live, rid: str, doc: str = DOC) -> dict:
    """Build the request with the client's own code, then post it ourselves.

    Returns ``receipt`` as a convenience alias for ``body["receipt"]``, since the
    success envelope nests it. On a refusal there is no receipt and the error
    body is left as-is for the caller to inspect.
    """
    node = _node(live, rid)
    eph_pub, eph_sec = pqc.kem_keypair(pqc.KEM)
    dr = node.build_request(doc, eph_pub)
    r = httpx.post(f"{live['base']}/open", json=dr.__dict__, timeout=30.0)
    body = r.json() if r.content else None
    return {"status": r.status_code, "body": body,
            "receipt": (body or {}).get("receipt"),
            "eph_sec": eph_sec, "request": dr}


# --------------------------------------------------------------------------
# The processes are real
# --------------------------------------------------------------------------

def test_the_witnesses_are_separate_processes_that_answer(live):
    assert len(live["fleet"].alive()) == 3
    for i, port in enumerate(live["ports"], start=1):
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=10.0)
        assert r.status_code == 200
        assert r.json()["witness_id"] == f"w{i}"


def test_the_authority_is_a_separate_process(live):
    """The fixture's central claim: a socket, not a method call."""
    assert live["proc"].poll() is None
    health = httpx.get(f"{live['base']}/health", timeout=10.0).json()
    assert health["min_witnesses"] == 2
    assert sorted(health["witnesses"]) == ["w1", "w2", "w3"]


def test_the_authority_sees_three_distinct_witnesses(live, api):
    """Distinct keys, not one key reported three times.

    A quorum of three copies of one key is a quorum of one, and it would look
    identical from the authority's side unless the keys are actually compared.
    """
    r = api.get("/witnesses").json()
    assert len(r["witnesses"]) == 3
    assert all(w["reachable"] for w in r["witnesses"])
    pubs = {w["pub"] for w in r["witnesses"]}
    assert len(pubs) == 3, "the witnesses do not have distinct keys"
    # And they match each witness's own state file, not anything the authority
    # chose to publish.
    assert pubs == {v.hex() for v in live["dep"].witness_pubs().values()}


# --------------------------------------------------------------------------
# A complete open, end to end
# --------------------------------------------------------------------------

def test_a_full_open_returns_a_usable_one_time_key(live):
    """The document actually opens, and the key is wrapped to this session only."""
    res = _open_over_http(live, "alice")
    assert res["status"] == 200, res["body"]
    receipt = res["receipt"]

    # The one-time key opens under this session's ephemeral secret...
    content_key = onetime.unwrap_session(res["eph_sec"], receipt["one_time_key"])
    # ...and that key decrypts the document that was actually sealed.
    plain = decrypt_document({"doc_id": receipt["doc_id"],
                              "cipher": receipt["cipher"],
                              "nonce": receipt["nonce"],
                              "ciphertext": receipt["ciphertext"]}, content_key)
    assert plain == TEXT
    assert receipt["attribution_caveat"] == ATTRIBUTION_CAVEAT


def test_the_receipt_chains_to_a_head_the_witnesses_actually_signed(live):
    """Every co-signature must verify over the published head.

    This is the property the whole ledger rests on: a witness signature is over
    the same ``STH.tbs()`` the log signed, so a third party holding the head can
    check it. If the wire format dropped or renamed the timestamp, the signatures
    would still be present and would simply never verify -- a failure that would
    otherwise surface only at a verification much later.
    """
    res = _open_over_http(live, "bob")
    receipt = res["receipt"]
    sth = STH.from_dict(receipt["sth"])
    pubs = live["dep"].witness_pubs()

    assert len(sth.witness_sigs) >= 2
    for wid, sig in sth.witness_sigs.items():
        assert pqc.verify(pubs[wid], sth.tbs(), bytes.fromhex(sig)), \
            f"witness {wid}'s co-signature does not verify over the head"
    assert pqc.verify(bytes.fromhex(_head(live)["log_pub"]), sth.tbs(),
                      bytes.fromhex(sth.log_sig))

    # And the entry is genuinely in that tree, checked against a leaf read back
    # over HTTP rather than from the server's memory.
    committed = _entry(live, receipt["index"])
    assert committed["leaf_hash"] == merkle.leaf_hash(
        committed["leaf"].encode("utf-8")).hex(), \
        "the entry endpoint's own leaf and leaf_hash disagree"
    assert merkle.verify_inclusion(
        committed["leaf"].encode("utf-8"), receipt["index"], receipt["tree_size"],
        [bytes.fromhex(p) for p in committed["inclusion_proof"]],
        bytes.fromhex(sth.root_hash))


def test_the_watermark_seed_is_the_committed_entry(live):
    """Recompute the seed from the ledger, as the leak-check pipeline does.

    If this holds, the mark on the recipient's copy is a function of the entry
    that authorised the release, so the two cannot drift apart -- which is the
    claim that makes a recovered mark attributable to a specific open.
    """
    from logfirst.crypto.kdf import watermark_seed

    res = _open_over_http(live, "carol")
    receipt = res["receipt"]
    committed = _entry(live, receipt["index"])
    leaf_hash = merkle.leaf_hash(committed["leaf"].encode("utf-8"))
    assert receipt["leaf_hash"] == leaf_hash.hex()
    assert receipt["watermark_seed"] == watermark_seed(leaf_hash).hex()


def test_successive_opens_are_independent(live):
    """Two opens of one document by one recipient share nothing."""
    a = _open_over_http(live, "alice")["receipt"]
    b = _open_over_http(live, "alice")["receipt"]
    assert a["leaf_hash"] != b["leaf_hash"]
    assert a["watermark_seed"] != b["watermark_seed"]
    assert a["one_time_key"] != b["one_time_key"]

    # A captured response is inert without the ephemeral secret, which no longer
    # exists anywhere: there is no long-lived recipient key that could open a
    # recording of the traffic.
    _, other_sec = pqc.kem_keypair(pqc.KEM)
    with pytest.raises(Exception):
        key = onetime.unwrap_session(other_sec, a["one_time_key"])
        decrypt_document({"doc_id": a["doc_id"], "nonce": a["nonce"],
                          "ciphertext": a["ciphertext"]}, key)


def test_the_client_node_opens_through_its_own_code_path(live):
    """Go through ``ClientNode.open`` rather than hand-posting the request.

    The tests above build the request with the client and post it themselves, so
    they would not catch a bug in the client's own unwrap-and-decrypt path. This
    one would -- and it is the only test in the file that uses the client's own
    transport, so it is also what proves the node can reach the authority at all.
    """
    node = _node(live, "alice")
    out = node.open(DOC)
    assert out["plaintext"] == TEXT
    assert out["ledger_index"] >= 0
    assert out["watermark_seed"]
    assert out["caveat"] == ATTRIBUTION_CAVEAT


# Long enough to carry a mark. The marker density is about one slot per 14
# running words (measured; see README), and a ledger pointer at 3x repetition
# needs 120 slots, so anything under roughly 1,600 words cannot carry one at
# all. That is a real capacity limit of the scheme, not a test convenience.
LONG = ("The quarterly assessment records that the northern corridor remains "
        "the primary route for materiel movement and that resupply intervals "
        "have shortened since the previous reporting period although the "
        "eastern depot continues to operate below its established capacity "
        "for the third consecutive month. ")
LONG_TEXT = LONG * 40
LONG_DOC = "DOC-LONG"


def test_a_marked_copy_differs_from_the_plaintext(live, api):
    """The artefact the recipient keeps is the marked one.

    Worth an end-to-end check because marking is where the ledger entry finally
    turns into something on the page: if the seed never reached the embedder,
    every other test in this file would still pass.
    """
    r = api.post("/documents", json={"doc_id": LONG_DOC,
                                     "classification": "SECRET",
                                     "text": LONG_TEXT,
                                     "recipients": ["carol"]})
    assert r.status_code == 200, r.text

    node = _node(live, "carol")
    out = node.open(LONG_DOC, mark=True)
    assert out["plaintext"] == LONG_TEXT
    plan = out["marking_plan"]
    assert plan["ok"], plan.get("reason")
    assert plan["pointer_slots"] > 0
    # A mark that changed nothing would be indistinguishable from no mark.
    assert out["marked_text"] != LONG_TEXT
    # The words are the same; only synonyms at marker positions differ, so the
    # copy must not gain or lose content.
    assert len(out["marked_text"].split()) == len(LONG_TEXT.split())


def test_a_document_too_short_to_mark_is_refused_rather_than_silently_unmarked(
        live):
    """A document below the capacity must say so.

    The quiet alternative -- embedding nothing and returning the plaintext as
    though it were marked -- would be the worst outcome available: the recipient
    keeps an unmarked copy while the ledger records a mark that was never
    applied, and an investigator later recovers nothing from a leak with no
    indication that anything went wrong. The refusal reason is part of the
    contract, so it is asserted, not just the boolean.
    """
    node = _node(live, "carol")
    out = node.open(DOC, mark=True)          # 26 words, 2 slots
    plan = out["marking_plan"]
    assert plan["ok"] is False
    assert "slot" in plan["reason"], plan["reason"]
    assert out["marked_text"] == out["plaintext"], \
        "an unmarkable document must be returned unchanged, not partly marked"
    # The open itself still succeeds and is still on the ledger: capacity to
    # carry a watermark is not a condition of decryption.
    assert out["ledger_index"] >= 0
    assert out["watermark_seed"]


# --------------------------------------------------------------------------
# Fail-closed, over the wire
# --------------------------------------------------------------------------

def test_killing_the_witnesses_fails_the_open_closed(live):
    """Kill the processes, then ask to open. Nothing may be released.

    Three separate claims, and the last two are the ones that matter most:

    1. the response is a refusal (503), not a key;
    2. the message says fail-closed, so this is distinguishable from an
       authorisation denial;
    3. **the ledger did not grow.** A leaf committed despite the quorum failing
       would mean the ordering was not enforced -- the entry would exist
       authorising a release that never happened. Checking the tree size is what
       distinguishes "refused" from "refused but recorded anyway";
    4. **no session was recorded either**, so the authority's own record of what
       it released does not claim a release that did not happen.
    """
    before_size = _size(live)
    before_sessions = len(_sessions(live))

    live["fleet"].kill(["w1", "w2", "w3"])
    try:
        res = _open_over_http(live, "alice")
        assert res["status"] == 503, res["body"]
        assert "fail-closed" in json.dumps(res["body"])
        assert "one_time_key" not in json.dumps(res["body"])
        assert "receipt" not in (res["body"] or {})

        assert _size(live) == before_size, \
            "a leaf was committed even though the witness quorum failed"
        assert len(_sessions(live)) == before_sessions, \
            "a session was recorded for an open that released nothing"
    finally:
        live["fleet"].start()
        _wait_relisten(live)


def test_the_refusal_explains_which_witnesses_were_unreachable(live):
    """An operator has to be able to find out why a release was refused.

    The per-witness reasons exist only on this path -- on success they come back
    in the response, but on failure the exception carries them and nothing else
    does. Dropping them would leave "quorum not met" with no way to tell a dead
    witness from a refusing one.
    """
    live["fleet"].kill(["w1", "w2", "w3"])
    try:
        res = _open_over_http(live, "bob")
        detail = res["body"]["detail"]
        assert "no leaf committed" in detail
        assert "/2 witnesses co-signed" in detail, detail
        assert "w1" in detail
    finally:
        live["fleet"].start()
        _wait_relisten(live)


def test_one_witness_down_still_opens_and_reports_the_refusal(live):
    """The mirror: a single dead witness must not stop the service.

    Without this, an implementation that failed whenever *any* witness was down
    would pass every fail-closed test in this file while being unusable.
    """
    live["fleet"].kill(["w3"])
    try:
        res = _open_over_http(live, "carol")
        assert res["status"] == 200, res["body"]
        receipt = res["receipt"]
        assert len(receipt["sth"]["witness_sigs"]) == 2
        assert any(r["witness_id"] == "w3"
                   for r in receipt["witness_refusals"])
    finally:
        live["fleet"].start(["w3"])
        _wait_relisten(live)


def _wait_relisten(live, timeout: float = 30.0):
    """Wait for restarted witnesses to answer before the next test runs.

    A witness killed and restarted needs a moment to bind. Without this the next
    test can race it and see an unreachable witness it did not intend to kill,
    which would look like a fail-closed bug rather than a timing artifact.
    """
    deadline = time.time() + timeout
    for port in live["ports"]:
        while time.time() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health",
                             timeout=0.5).status_code == 200:
                    break
            except Exception:
                time.sleep(0.15)
        else:
            raise AssertionError(f"witness on port {port} never came back")


# --------------------------------------------------------------------------
# Authorisation refusals
# --------------------------------------------------------------------------

def test_an_unknown_recipient_is_refused(live):
    """A real key, signed properly, for an identity the authority never issued.

    The refusal must be the identity check. A test that only sent a garbage
    signature would pass against an implementation that never looked at the
    certificate at all.
    """
    _, sec = pqc.sig_keypair(pqc.SIG)
    node = _node(live, "alice")
    node.recipient_id = "mallory"
    node.sig_sec = sec
    eph_pub, _ = pqc.kem_keypair(pqc.KEM)
    dr = node.build_request(DOC, eph_pub)
    r = httpx.post(f"{live['base']}/open", json=dr.__dict__, timeout=30.0)
    assert r.status_code == 403
    assert "unknown-recipient" in r.json()["detail"]


def test_a_known_recipient_without_a_grant_is_refused(live):
    """Default-deny: the identity is fine, the authorisation is not.

    ``alice`` is a real recipient, but ``DOC-UNGRANTED`` was sealed to nobody --
    so this isolates the grant check from the identity check, which is the
    distinction a default-allow implementation would fail.
    """
    res = _open_over_http(live, "alice", UNGRANTED)
    assert res["status"] == 403, res["body"]
    assert "not-authorized-for-document" in res["body"]["detail"]


def test_an_unsigned_or_forged_request_is_refused(live):
    """The non-repudiation check is what stops a request being made up."""
    node = _node(live, "alice")
    eph_pub, _ = pqc.kem_keypair(pqc.KEM)
    dr = node.build_request(DOC, eph_pub)

    for body, reason in (
        (dict(dr.__dict__, sig=""), "unsigned-request"),
        # Signed by somebody else's key: a valid signature, wrong signer.
        (dict(dr.__dict__, sig=pqc.sign(pqc.sig_keypair(pqc.SIG)[1], dr.tbs(),
                                        pqc.SIG).hex()),
         "bad-request-signature"),
        # A valid signature over a different body: the ephemeral key swapped.
        (dict(dr.__dict__,
              sig=pqc.sign(node.sig_sec,
                           DecryptionRequest(
                               doc_id=dr.doc_id, recipient_id=dr.recipient_id,
                               nonce=dr.nonce, timestamp=dr.timestamp,
                               device_fp=dr.device_fp,
                               ephemeral_kem_pub=pqc.kem_keypair(pqc.KEM)[0].hex()
                           ).tbs(), pqc.SIG).hex()),
         "bad-request-signature"),
    ):
        r = httpx.post(f"{live['base']}/open", json=body, timeout=30.0)
        assert r.status_code == 403, (reason, r.text)
        assert reason in r.json()["detail"], (reason, r.json()["detail"])


def test_a_revoked_recipient_is_refused(live):
    """Revocation is checked against the authority's store, not the client's say."""
    _set_revoked(live, "bob", True)
    try:
        res = _open_over_http(live, "bob")
        assert res["status"] == 403, res["body"]
        assert "recipient-revoked" in res["body"]["detail"]
    finally:
        _set_revoked(live, "bob", False)


def test_no_refusal_leaves_a_ledger_entry(live):
    """None of the authorisation failures may write to the ledger.

    Cheap to get wrong: the natural implementation appends after checking, but an
    implementation that logged "attempted open" would grow the tree on every
    failure -- and the tree size is exactly what the fail-closed test above
    relies on.
    """
    before = _size(live)
    node = _node(live, "alice")
    eph_pub, _ = pqc.kem_keypair(pqc.KEM)
    dr = node.build_request("DOC-DOES-NOT-EXIST", eph_pub)
    r = httpx.post(f"{live['base']}/open", json=dr.__dict__, timeout=30.0)
    assert r.status_code in (403, 404)
    assert _size(live) == before


# --------------------------------------------------------------------------
# The witness refusing over the wire
# --------------------------------------------------------------------------

def test_a_witness_refuses_a_rollback_over_http_with_409(live):
    """A refusal is a 409, not a 500 and not a 200.

    500 would read as a transient fault and invite a retry; 200 would be worse.
    The authority's client maps 409 to ``WitnessUnavailable``, which is what
    reduces the quorum -- so the status code is load-bearing, not cosmetic.

    Size 0 is used because it is smaller than anything any witness has signed
    *and* a size none of them has signed at all. Asking for a smaller size they
    had already signed would be caught by the equivocation rule first, since the
    root would necessarily differ -- which is why the rollback rule needs its own
    reachable case.
    """
    head = _head(live)
    r = httpx.post(f"http://127.0.0.1:{live['ports'][0]}/cosign",
                   json={"tree_size": 0, "root_hash": head["root"],
                         "timestamp": "2026-01-01T00:00:00+00:00",
                         "consistency_proof": []}, timeout=20.0)
    assert r.status_code == 409, r.text
    assert "ROLLBACK" in r.json()["detail"]
    assert head["tree_size"] >= 1


def test_a_witness_refuses_equivocation_over_http_with_409(live):
    """The split-view attack, refused at the socket.

    A different root at a size the witness has already signed is the one thing a
    witness must never agree to; two signatures at one size over different roots
    are themselves proof of misbehaviour.
    """
    head = _head(live)
    r = httpx.post(f"http://127.0.0.1:{live['ports'][1]}/cosign",
                   json={"tree_size": head["tree_size"],
                         "root_hash": "ab" * 32,
                         "timestamp": "2026-01-01T00:00:00+00:00",
                         "consistency_proof": []}, timeout=20.0)
    assert r.status_code == 409, r.text
    assert "EQUIVOCATION" in r.json()["detail"], r.json()["detail"]


def test_resigning_the_same_head_over_http_is_idempotent(live):
    """A retried co-sign request must not be read as an attack.

    The head is the one the witnesses signed for the current tree, so this is a
    genuine retry: a dropped response and a second attempt must return the same
    signature rather than a refusal that would wedge the log.
    """
    head = _head(live)
    sth = head["sth"]
    body = {"tree_size": sth["tree_size"], "root_hash": sth["root_hash"],
            "timestamp": sth["timestamp"], "consistency_proof": []}
    r = httpx.post(f"http://127.0.0.1:{live['ports'][0]}/cosign", json=body,
                   timeout=20.0)
    assert r.status_code == 200, r.text
    assert r.json()["already_signed"] is True
    # The signature it returns is the one it already gave, and it must verify
    # against the head the log published.
    pubs = live["dep"].witness_pubs()
    assert pqc.verify(pubs["w1"], STH.from_dict(sth).tbs(),
                      bytes.fromhex(r.json()["sig"]))


# --------------------------------------------------------------------------
# The ledger surface the demo and the verifier read
# --------------------------------------------------------------------------

def test_the_ledger_endpoints_agree_with_each_other(live, api):
    head = api.get("/ledger/head").json()
    assert head["tree_size"] >= 1
    assert head["root"] and head["log_pub"]
    assert head["min_witnesses"] == 2

    entries = api.get("/ledger/entries", params={"limit": 5}).json()
    assert entries["tree_size"] == head["tree_size"]
    for e in entries["entries"]:
        assert e["leaf_hash"] == merkle.leaf_hash(
            e["leaf"].encode("utf-8")).hex()

    one = api.get("/ledger/entry/0").json()
    assert json.loads(one["leaf"])["kind"] == "decryption-request"
    # The proof at a size folds to that size's root, which is what makes it
    # checkable against a historical head rather than only against today's.
    assert merkle.verify_inclusion(
        one["leaf"].encode("utf-8"), 0, one["tree_size"],
        [bytes.fromhex(p) for p in one["inclusion_proof"]],
        bytes.fromhex(one["root"]))


def test_the_ledger_entry_carries_the_source_and_the_signature(live):
    """The entry is the signed request plus where it came from.

    The source address is recorded because the authority is network-facing, but
    it is unauthenticated metadata. The test asserts it is present *and* that the
    signature is, so the two are visibly different kinds of evidence -- and then
    checks the signature, which is the part that carries weight.
    """
    res = _open_over_http(live, "carol")
    leaf = json.loads(_entry(live, res["receipt"]["index"])["leaf"])
    assert leaf["kind"] == "decryption-request"
    assert leaf["source_ip"]
    assert leaf["request"]["sig"]

    dr = DecryptionRequest(**leaf["request"])
    assert pqc.verify(bytes.fromhex(live["dep"].cert_for("carol").sig_pub),
                      dr.tbs(), bytes.fromhex(dr.sig))


def test_the_ledger_survives_the_authority_restarting(live):
    """A restarted authority must reproduce the same heads.

    The log's key is read from its own database, so a restart that regenerated
    it would invalidate every signature it had ever published -- and the symptom
    would be a verification failure much later, after the evidence was relied on.
    """
    before = _head(live)
    live["proc"].terminate()
    live["proc"].wait(timeout=10)
    live["proc"] = proc_mod.Popen(
        [sys.executable, "-m", "logfirst.authority.server",
         "--data", live["dep"].data_dir, "--port", str(live["auth_port"]),
         "--no-tls",
         "--witness-ports", ",".join(str(p) for p in live["ports"]),
         "--min-witnesses", "2"],
        cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    _wait_http(live["auth_port"])

    after = _head(live)
    assert after["tree_size"] == before["tree_size"]
    assert after["root"] == before["root"]
    assert after["log_pub"] == before["log_pub"]

    # And it still works: a fresh open appends and is witnessed.
    res = _open_over_http(live, "alice")
    assert res["status"] == 200, res["body"]
    assert res["receipt"]["tree_size"] == before["tree_size"] + 1


def test_anchoring_over_http_pins_a_root(live, api):
    """The externalized root is signed by the slow, conservative algorithm.

    ``verify_anchor`` checks the record against the public key embedded in it,
    which shows only that the record is internally consistent -- not that the key
    is the real anchor key. So this also checks it against the key read from the
    anchor's own keyfile, which is the out-of-band source a verifier must pin.
    """
    from logfirst.ledger.anchor import verify_anchor
    from logfirst.models import canon

    r = api.post("/anchor")
    assert r.status_code == 200, r.text
    rec = r.json()["anchor"]
    head = api.get("/ledger/head").json()
    assert rec["tree_size"] == head["tree_size"]
    assert rec["root_hash"] == head["root"]
    assert rec["alg"] == pqc.ANCHOR_SIG
    assert verify_anchor(rec)

    pinned = live["dep"].anchorer().anchor_pub
    assert bytes.fromhex(rec["anchor_pub"]) == pinned
    tbs = canon({"tree_size": rec["tree_size"], "root_hash": rec["root_hash"],
                 "timestamp": rec["timestamp"], "alg": rec["alg"]})
    assert pqc.verify(pinned, tbs, bytes.fromhex(rec["anchor_sig"]),
                      pqc.ANCHOR_SIG)


def test_the_mtls_material_was_actually_issued(live):
    """The deployment issues real node certificates, not placeholders.

    The authority is network-facing, so the transport is part of the design even
    though this file bypasses it with ``--no-tls``. If issuance silently produced
    nothing, the demo's TLS would be the only thing that noticed.
    """
    issued = live["dep"].issue_node_cert("authority")
    for key in ("cert", "key", "ca"):
        assert os.path.exists(issued[key]), f"{key} was not written"
        assert os.path.getsize(issued[key]) > 0
