"""The device fingerprint: real values, carried end to end, and not trusted.

The interesting thing about this field is the gap between what it is and what it
looks like. It sits inside ``DecryptionRequest.tbs()``, so the recipient's
ML-DSA-65 signature covers it; it sits inside ``leaf_bytes()``, so it is in the
ledger leaf; and it is now persisted on the session row and shown in the
register. All of that makes it *tamper-evident* -- a recipient cannot deny
having asserted that value -- and none of it makes it *true*, because the
recipient chooses it and no hardware is read. The tests below pin both halves:
that the value is real and travels, and that the authority still does not act on
it.

The one thing that was genuinely broken and is fixed here: every demo entry
recorded the same constant, ``"unbound-device"``, so the field was present in
every leaf and said nothing about anything.
"""

from __future__ import annotations

import json
import re

import pytest

from logfirst.client.node import ClientNode
from logfirst.crypto import pqc
from logfirst.data.deploy import Deployment
from logfirst.models import DecryptionRequest

from tests.conftest import make_witnesses

pytest.importorskip("fastapi")

FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{32}$")


@pytest.fixture(scope="module")
def dep(tmp_path_factory):
    """A deployment on disk, with recipients enrolled and no witnesses started.

    Nothing here needs a running authority: the fingerprint is minted at
    enrolment and asserted by the client, which is exactly the property under
    test.
    """
    data = str(tmp_path_factory.mktemp("dep"))
    d = Deployment.create(data, witness_ports=[0, 0, 0], min_witnesses=2)
    for r in ("alice", "bob", "carol"):
        d.add_recipient(r)
    return d


# ==========================================================================
# The value is real
# ==========================================================================

def test_every_enrolled_recipient_gets_a_fingerprint(dep):
    """Not the constant, and shaped like a fingerprint.

    ``"unbound-device"`` was the default on ``ClientNode`` and nothing ever
    passed anything else, so every ledger entry in the demo recorded that same
    string. A field that is always the same value is worse than an absent one:
    it renders, it looks like evidence, and it distinguishes nothing.
    """
    for rid in ("alice", "bob", "carol"):
        fp = dep.device_fp_for(rid)
        assert fp != "unbound-device"
        assert FINGERPRINT.match(fp), fp


def test_two_recipients_have_different_fingerprints(dep):
    """Per-device means distinguishable, or the column tells you nothing."""
    fps = {rid: dep.device_fp_for(rid) for rid in ("alice", "bob", "carol")}
    assert len(set(fps.values())) == 3, fps


def test_the_fingerprint_is_read_from_disk_rather_than_re_minted(dep):
    """Stability across a restart, which is what makes it a device identity.

    Re-minting on each read would give a recipient a new "device" every time the
    demo started, so two ledger entries a day apart would name different
    machines for the same person -- and the register's enrolled-vs-asserted
    column would show a permanent, meaningless mismatch.
    """
    before = dep.device_fp_for("alice")

    # A restart, as far as this file is concerned: a new instance reading the
    # same directory.
    restarted = Deployment(dep.data_dir)
    assert restarted.device_fp_for("alice") == before

    # And the value is on disk, so it survives the process entirely.
    people = json.loads(open(dep.path("recipients.json"), encoding="utf-8").read())
    assert people["alice"]["device"]["fingerprint"] == before


def test_an_older_deployment_is_backfilled_without_touching_its_keys(tmp_path):
    """The upgrade path for a ``recipients.json`` written before this existed.

    The tempting fix -- re-enrol the recipients -- would mint fresh keypairs and
    invalidate every certificate the ledger already references. The fingerprint
    is added beside the existing keys instead, and written back so the value is
    stable from then on.
    """
    d = Deployment.create(str(tmp_path / "old"), witness_ports=[0, 0, 0],
                          min_witnesses=1)
    d.add_recipient("alice")

    # Rewrite the file as the previous version would have left it.
    people = json.loads(open(d.path("recipients.json"), encoding="utf-8").read())
    del people["alice"]["device"]
    with open(d.path("recipients.json"), "w", encoding="utf-8") as fh:
        json.dump(people, fh)
    cert_before = people["alice"]["cert"]
    secrets_before = people["alice"]["secrets"]

    fp = Deployment(d.data_dir).device_fp_for("alice")
    assert FINGERPRINT.match(fp)

    after = json.loads(open(d.path("recipients.json"), encoding="utf-8").read())
    assert after["alice"]["cert"] == cert_before, (
        "the backfill changed the certificate, which would invalidate every "
        "ledger entry that already names it")
    assert after["alice"]["secrets"] == secrets_before
    # Persisted, not just returned: the second read must not re-mint.
    assert Deployment(d.data_dir).device_fp_for("alice") == fp


def test_an_unknown_recipient_is_an_error_not_an_invented_value(tmp_path):
    """KeyError, so a caller cannot get a plausible-looking fingerprint for
    somebody who was never enrolled."""
    d = Deployment.create(str(tmp_path / "d"), witness_ports=[0, 0, 0],
                          min_witnesses=1)
    with pytest.raises(KeyError):
        d.device_fp_for("nobody")


# ==========================================================================
# It travels: into the request, the signature, and the ledger leaf
# ==========================================================================

def _node(dep, rid):
    index = list(dep.recipients()).index(rid)
    return ClientNode(
        rid, dep.cert_for(rid),
        bytes.fromhex(dep.secrets_for(rid)["sig_sec"]),
        authority_url="http://127.0.0.1:1",
        device_fp=dep.device_fp_for(rid), user_index=index,
    )


def test_a_request_built_by_the_demo_node_carries_the_enrolled_fingerprint(dep):
    """The wiring, not the field: ``Scenario.node`` used to pass nothing."""
    node = _node(dep, "carol")
    assert node.device_fp == dep.device_fp_for("carol")
    assert node.device_fp != "unbound-device"

    pub, _ = pqc.kem_keypair(pqc.KEM)
    dr = node.build_request("DOC-0000", pub)
    assert dr.device_fp == dep.device_fp_for("carol")


def test_the_fingerprint_is_under_the_recipients_signature(dep):
    """Which is the only thing that makes it worth recording.

    The signature covers ``tbs()``, which includes the fingerprint. So the value
    in the ledger is one the recipient's key actually committed to -- they
    cannot later say the authority recorded a device they never claimed. What
    the signature does *not* establish is that the claim is true.
    """
    node = _node(dep, "alice")
    pub, _ = pqc.kem_keypair(pqc.KEM)
    dr = node.build_request("DOC-0000", pub)
    sig = bytes.fromhex(dr.sig)
    assert pqc.verify(bytes.fromhex(dep.cert_for("alice").sig_pub), dr.tbs(), sig)

    # Change only the device fingerprint and the same signature must stop
    # verifying. If it did not, the field would be outside the signed body and
    # the ledger's device attribution would be editable by whoever holds it.
    swapped = DecryptionRequest(**{**dr.__dict__, "device_fp": "sha256:" + "0" * 32})
    assert swapped.tbs() != dr.tbs()
    assert not pqc.verify(bytes.fromhex(dep.cert_for("alice").sig_pub),
                          swapped.tbs(), sig)


def test_the_fingerprint_reaches_the_ledger_leaf_and_the_session_row(tmp_path):
    """End to end through a real append, with an in-process quorum.

    The leaf is what an investigator reads, and the session row is what the
    register reads. Both must carry the asserted value, or one of the two screens
    is showing something the other cannot corroborate.
    """
    from logfirst.authority.server import Authority
    from logfirst.authority.store import Store
    from logfirst.crypto.ca import CA, enroll_recipient
    from logfirst.ledger.log import LedgerLog
    from logfirst.ledger.witnesses import WitnessQuorum

    ca = CA.create()
    cert, secrets = enroll_recipient(ca, "carol")
    store = Store.open(str(tmp_path / "store.db"))
    store.add_recipient(cert)

    pub, sec = pqc.sig_keypair(pqc.SIG)
    server_kem_pub, server_kem_sec = pqc.kem_keypair(pqc.KEM)
    quorum = WitnessQuorum(make_witnesses(tmp_path, 3), min_witnesses=2)
    log = LedgerLog.open(str(tmp_path / "ledger.db"), quorum)
    auth = Authority(log, store, ca.sig_pub, server_kem_pub, server_kem_sec)

    auth.seal(b"the annex is unremarkable and says nothing of interest. " * 20,
              "DOC-0000", "internal", ["carol"])

    node = ClientNode("carol", cert, bytes.fromhex(secrets["sig_sec"]),
                      authority_url="http://127.0.0.1:1",
                      device_fp="sha256:" + "ab" * 16)
    eph_pub, _ = pqc.kem_keypair(pqc.KEM)
    receipt = auth.open_document(node.build_request("DOC-0000", eph_pub),
                                 source_ip="127.0.0.1")

    leaf = json.loads(log.get_leaf(receipt["index"]).decode("utf-8"))
    assert leaf["request"]["device_fp"] == "sha256:" + "ab" * 16, (
        "the fingerprint the client asserted is not in the ledger leaf")

    rows = store.sessions_for("carol")
    assert len(rows) == 1
    assert rows[0]["device_fp"] == "sha256:" + "ab" * 16, (
        "the session row did not keep the fingerprint, so the register cannot "
        "show what the ledger already records")


def test_the_authority_records_the_fingerprint_without_acting_on_it(tmp_path):
    """The deliberate absence, asserted so it is not mistaken for an oversight.

    Two opens asserting two different fingerprints both succeed. A device check
    would refuse the second; the design records it instead, because a
    client-asserted value that can refuse an open is a value an attacker simply
    changes. If this test ever fails, someone has added enforcement -- which is a
    different feature with a different threat model, not a hardening.
    """
    from logfirst.authority.server import Authority
    from logfirst.authority.store import Store
    from logfirst.crypto.ca import CA, enroll_recipient
    from logfirst.ledger.log import LedgerLog
    from logfirst.ledger.witnesses import WitnessQuorum

    ca = CA.create()
    cert, secrets = enroll_recipient(ca, "carol")
    store = Store.open(str(tmp_path / "store.db"))
    store.add_recipient(cert)

    pub, sec = pqc.sig_keypair(pqc.SIG)
    server_kem_pub, server_kem_sec = pqc.kem_keypair(pqc.KEM)
    quorum = WitnessQuorum(make_witnesses(tmp_path, 3), min_witnesses=2)
    auth = Authority(LedgerLog.open(str(tmp_path / "ledger.db"), quorum), store,
                     ca.sig_pub, server_kem_pub, server_kem_sec)
    auth.seal(b"a document that two different machines will open. " * 20,
              "DOC-0000", "internal", ["carol"])

    for fp in ("sha256:" + "11" * 16, "sha256:" + "22" * 16):
        node = ClientNode("carol", cert, bytes.fromhex(secrets["sig_sec"]),
                          authority_url="http://127.0.0.1:1", device_fp=fp)
        eph_pub, _ = pqc.kem_keypair(pqc.KEM)
        auth.open_document(node.build_request("DOC-0000", eph_pub))

    seen = {r["device_fp"] for r in store.sessions_for("carol")}
    assert seen == {"sha256:" + "11" * 16, "sha256:" + "22" * 16}, (
        "the authority did not record both asserted values; the register's "
        "enrolled-vs-asserted column is how a mismatch becomes visible")
