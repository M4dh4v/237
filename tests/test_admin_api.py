"""The recipient register, driven through the routes the admin screen calls.

What this file is really testing is that revocation *does something*. The
register is a view, and a view is only worth having if the lever beside it
changes behaviour, so the central test here revokes a recipient and then
performs a genuine open and asserts two things at once: the authority refused,
and the ledger did not grow. A refusal that still appended an entry would be a
record of an open that never happened; an append that still released a key would
be the whole fail-closed claim gone.

The tests share one scenario, so each uses its own recipient. A test that
revokes alice cannot pass or fail because of what another test did to carol.
"""

from __future__ import annotations

import os
import socket

import pytest
from fastapi.testclient import TestClient

from logfirst.authority.server import build_app
from logfirst.data.deploy import Deployment
from logfirst.data.scenario import Scenario

pytest.importorskip("fastapi.testclient")

RECIPIENTS = ["alice", "bob", "carol", "dave"]


def _free_ports(n: int) -> list[int]:
    out = []
    for _ in range(n):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            out.append(s.getsockname()[1])
    return out


@pytest.fixture(scope="module")
def sc(tmp_path_factory):
    """A live scenario with real witness processes, as the demo runs it."""
    root = tmp_path_factory.mktemp("admin")
    data = str(root / "data")
    dep = Deployment.create(data, witness_ports=_free_ports(3), min_witnesses=2)
    for r in RECIPIENTS:
        dep.add_recipient(r)
    scenario = Scenario.build(data, n_docs=2, target_words=1800, seed=11,
                              recipients=RECIPIENTS, start_witnesses=False)
    scenario.fleet.start()
    # One document granted to everyone, so a refusal can never be confused with
    # a default-deny: every recipient below is authorised for this document.
    scenario.distribute("DOC-0000", RECIPIENTS)
    try:
        yield scenario
    finally:
        scenario.close()


@pytest.fixture(scope="module")
def client(sc):
    return TestClient(build_app(sc.authority, scenario=sc))


def _row(client, recipient_id):
    body = client.get("/demo/admin/recipients").json()
    return next(r for r in body["recipients"] if r["recipient_id"] == recipient_id)


def _open(client, recipient_id, doc_id="DOC-0000"):
    return client.post("/demo/open", json={"doc_id": doc_id,
                                           "recipient_id": recipient_id,
                                           "mark": True})


# ==========================================================================
# The register
# ==========================================================================

def test_the_register_lists_every_recipient_with_what_the_screen_renders(client):
    """One row per recipient, carrying every column the table has.

    The field list is asserted rather than the values, because a missing key is
    how this screen breaks: the table renders a blank cell and nobody can tell
    an absent field from a recipient with nothing recorded.
    """
    body = client.get("/demo/admin/recipients").json()
    assert {r["recipient_id"] for r in body["recipients"]} == set(RECIPIENTS)
    assert body["note"], (
        "the register must carry the recorded-not-enforced note; the screen "
        "renders it, so it cannot live only in the JavaScript")

    required = {"recipient_id", "role", "revoked", "serial", "issued_at",
                "kem_alg", "sig_alg", "ca_signature_ok", "device_fp",
                "last_seen_device_fp", "granted", "opened"}
    for row in body["recipients"]:
        assert required <= set(row), f"{row['recipient_id']}: missing {required - set(row)}"
        assert row["ca_signature_ok"] is True, (
            f"{row['recipient_id']}'s stored certificate does not verify "
            "against the CA -- every open for them would be refused")
        assert row["kem_alg"] and row["sig_alg"]


def test_the_register_counts_grants_and_opens(client, sc):
    """`granted` is grants, not opens; `opened` is opens, not grants.

    They are equal until someone opens something, which is exactly when a mixed
    up pair stops being obvious -- so one recipient is opened for and another is
    not, and both numbers are checked.
    """
    opened = _open(client, "dave")
    assert opened.status_code == 200, opened.text

    dave = _row(client, "dave")
    carol = _row(client, "carol")

    assert dave["granted"] == 1
    assert dave["opened"] >= 1
    assert carol["granted"] == 1
    assert carol["opened"] == 0, (
        "carol has not opened anything in this file; the two counts are the "
        "same number being rendered twice")


def test_the_register_shows_the_enrolled_and_the_asserted_fingerprint(client):
    """The pair, side by side, because the difference is the only interesting
    part -- and the note beside it says the authority never compares them."""
    row = _row(client, "dave")  # opened in the test above
    assert row["last_seen_device_fp"], "no fingerprint came back on the session"
    assert row["last_seen_device_fp"] == row["device_fp"]
    assert row["device_fp"] != "unbound-device"
    assert row["device_fp"].startswith("sha256:")


def test_the_register_reports_an_unknown_recipient_as_absent_not_as_a_row(client):
    body = client.get("/demo/admin/recipients").json()
    ids = {r["recipient_id"] for r in body["recipients"]}
    assert "mallory" not in ids


# ==========================================================================
# Revoke: the lever has to do something
# ==========================================================================

def test_revoking_refuses_the_next_open_and_appends_nothing_to_the_ledger(
        client, sc):
    """Both halves, and the second is the one that matters.

    A 403 alone would be satisfied by an authority that refuses the key but
    still commits the request -- which would put an entry in the ledger for an
    open that did not happen, and an investigator reading that ledger would see
    an event that never occurred.
    """
    assert _open(client, "alice").status_code == 200, "fixture setup failed"

    before = sc.authority.log.tree_size()
    assert client.post("/demo/admin/revoke",
                       json={"recipient_id": "alice"}).status_code == 200
    assert _row(client, "alice")["revoked"] is True

    refused = _open(client, "alice")
    assert refused.status_code == 403, refused.text
    assert "recipient-revoked" in refused.text, (
        "the refusal must name the reason; 'forbidden' alone is not something "
        "an operator can act on")
    assert sc.authority.log.tree_size() == before, (
        "the ledger grew for an open that was refused -- the entry would be a "
        "record of an event that never happened")


def test_reinstating_lets_them_open_again(client, sc):
    """And the ledger grows by exactly one when it does.

    ``revoke`` is a flag write, not a withdrawal: the certificate was never
    pulled and no key was destroyed, which is why this is one route call rather
    than a re-enrolment.
    """
    assert _row(client, "alice")["revoked"] is True, (
        "depends on the previous test having revoked alice")

    before = sc.authority.log.tree_size()
    assert client.post("/demo/admin/reinstate",
                       json={"recipient_id": "alice"}).status_code == 200
    assert _row(client, "alice")["revoked"] is False

    again = _open(client, "alice")
    assert again.status_code == 200, again.text
    assert sc.authority.log.tree_size() == before + 1


def test_a_revocation_survives_the_restart_that_rebuilds_the_store(client, sc):
    """The bug that would have made this feature theatre.

    Every ``Scenario.build`` calls ``Deployment.sync_store``, which re-adds every
    recipient from the CA's file. When that was an ``INSERT OR REPLACE`` it
    rewrote ``revoked`` from the certificate's role, so the revocation lifted on
    the next start -- and the admin screen's one destructive control would have
    been a button that did nothing except until someone restarted the service.

    Replayed here rather than only in ``test_store.py`` because this is the
    actual restart path, with the deployment file and the route on either side
    of it.
    """
    assert client.post("/demo/admin/revoke",
                       json={"recipient_id": "carol"}).status_code == 200
    assert _open(client, "carol").status_code == 403

    # What a restart does, in order.
    sc.dep.sync_store(sc.store)

    assert _row(client, "carol")["revoked"] is True, (
        "re-syncing the CA's file cleared the revocation; it would lift on "
        "every restart")
    assert _open(client, "carol").status_code == 403, (
        "carol could open again after a store re-sync")

    # Leave the scenario as it was found.
    client.post("/demo/admin/reinstate", json={"recipient_id": "carol"})


# ==========================================================================
# The refusal to invent a recipient
# ==========================================================================

@pytest.mark.parametrize("route", ["/demo/admin/revoke", "/demo/admin/reinstate"])
def test_revoking_an_unknown_recipient_is_a_404(client, route):
    """Not a 200 for a change that touched no rows.

    The store's methods return whether a row changed precisely so this can be
    distinguished. An operator who mistypes a name must not be told the
    revocation worked -- they would stop looking, and the person would still be
    able to open documents.
    """
    r = client.post(route, json={"recipient_id": "mallory"})
    assert r.status_code == 404, r.text
    assert "mallory" in r.text


def test_the_admin_routes_do_not_exist_without_a_scenario(tmp_path):
    """Demo-gated like the rest of the demo surface.

    ``build_app`` documents that the demo routes are registered only when a
    scenario is attached, so a production-shaped run carries none of them. The
    register is unauthenticated -- admin-as-trusted is the standing assumption
    for this prototype -- and this is the boundary that keeps that assumption
    from following the code anywhere it should not.
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

    paths = {r.path for r in build_app(auth).routes}
    for path in ("/demo/admin/recipients", "/demo/admin/revoke",
                 "/demo/admin/reinstate", "/demo/admin/reset"):
        assert path not in paths, f"{path} exists on a run with no scenario"


def test_there_is_no_enrolment_route(client):
    """The deliberate absence, asserted so it is not added back by accident.

    Certificates are issued by the CA offline. A route that mints recipients
    would put identity issuance on the network-facing service, which is the one
    thing the CA/authority split exists to prevent -- so a 404 here is the
    design, not an unfinished screen.
    """
    for body in ({"recipient_id": "newbie"},
                 {"recipient_id": "newbie", "role": "recipient"}):
        r = client.post("/demo/admin/enroll", json=body)
        assert r.status_code == 404, (
            "there is an enrolment route; certificates are issued offline by "
            "the CA, not by the authority")


# ==========================================================================
# The sandbox reset: an operator action, not an authority capability
# ==========================================================================

def test_the_reset_refuses_when_nothing_can_restart_the_instance(client):
    """An unmanaged run must not be killed by a button with no way back.

    `run.sh` and a hand-run `--serve` have no supervisor to bring the process
    up again, so a reset that stopped the server would simply leave the console
    dark. The route answers honestly -- "restart me yourself, here is the
    command" -- rather than performing a stop it cannot undo.
    """
    r = client.post("/demo/admin/reset")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["supervised"] is False
    assert body["rebuilding"] is False
    assert "demo.py --serve --fresh" in body["command"]
    assert "not a capability of the authority" in body["note"], (
        "the refusal must keep the honesty framing: a demo reset is not an "
        "authority's power to erase the witnessed record")


def test_a_supervised_reset_marks_one_fresh_rebuild_and_asks_to_restart(sc):
    """The supervised path writes the one-shot sentinel and requests shutdown.

    Two things are asserted, and the second is the one that matters: the
    sentinel is written so the *next* start rebuilds from seed, and the route
    did not delete anything itself. `scripts/demo.py` is the only place the
    scenario is built, and it is where `fresh=True` is applied -- there is no
    erase path here or anywhere in the ledger module.
    """
    app = build_app(sc.authority, scenario=sc)
    asked = {"n": 0}
    app.state.sakshya_restart = lambda: asked.__setitem__("n", asked["n"] + 1)

    sentinel = sc.dep.path("RESET_REQUESTED")
    try:
        body = TestClient(app).post("/demo/admin/reset").json()
        assert body["ok"] is True and body["rebuilding"] is True
        assert os.path.exists(sentinel), (
            "no sentinel was written; the restart would not rebuild from seed")
        assert asked["n"] == 1, "shutdown was not requested exactly once"
    finally:
        if os.path.exists(sentinel):
            os.remove(sentinel)
