"""The authority's operational database, on the two things that can go wrong.

This store is mutable state, not evidence -- nothing in the attribution path
trusts it -- so most of what it does is not worth a test. Two things are:

* **A revocation must survive a restart.** ``Deployment.sync_store`` re-adds
  every recipient from the CA's file every time a scenario is built, so if the
  upsert rewrote ``revoked`` from the certificate's role, revocation would undo
  itself on the next start. That is a defect that presents as "the admin button
  does nothing", which is exactly the kind of bug that gets shipped.
* **An existing ``store.db`` must gain a new column.** Every statement in the
  schema is ``CREATE TABLE IF NOT EXISTS``, so a database written by an earlier
  version keeps its shape forever and an added column never appears.

Both are tested by replaying the real sequence rather than by calling the
helper: the restart is simulated with a second ``Store`` on the same file, and
the upgrade with a database created the way the old version created it.
"""

from __future__ import annotations

import sqlite3

import pytest

from logfirst.authority.store import Store
from logfirst.crypto.ca import CA, enroll_recipient

pytest.importorskip("fastapi")


@pytest.fixture
def ca():
    return CA.create()


def _cert(ca, recipient_id: str, role: str = "recipient"):
    cert, _ = enroll_recipient(ca, recipient_id, role=role)
    return cert


# ==========================================================================
# Revocation, across a restart
# ==========================================================================

def test_re_adding_a_recipient_does_not_clear_a_revocation(tmp_path):
    """The bug the admin screen would have shipped.

    Revoking a recipient and then restarting the demo re-added every recipient
    from the deployment file. With ``INSERT OR REPLACE`` that rewrote the whole
    row, ``revoked`` included, so the revocation silently lifted -- and it would
    have lifted on every restart, which makes "revoke" a button that does
    nothing except until the next time someone restarts the service.
    """
    ca = CA.create()
    cert = _cert(ca, "carol")
    path = str(tmp_path / "store.db")

    store = Store.open(path)
    store.add_recipient(cert)
    assert store.revoke("carol") is True
    assert store.is_revoked("carol") is True

    # A restart: the same file, a new Store, and the sync that happens on every
    # Scenario.build.
    reopened = Store.open(path)
    reopened.add_recipient(cert)
    assert reopened.is_revoked("carol") is True, (
        "re-adding a recipient from the CA's file cleared their revocation; "
        "revoking would then undo itself on the next restart")

    # And the certificate really is still the one on file -- this is a refresh,
    # not a no-op.
    assert reopened.get_cert("carol").serial == cert.serial


def test_a_fresh_insert_still_takes_revoked_from_the_role(tmp_path):
    """The other half of the upsert: a first insert is unchanged behaviour.

    ``revoked`` has always come from the certificate's role on insert, and
    making revocation survive a restart must not change what a new recipient
    looks like.
    """
    ca = CA.create()
    store = Store.open(str(tmp_path / "store.db"))
    store.add_recipient(_cert(ca, "alice"))
    store.add_recipient(_cert(ca, "malory", role="revoked"))

    by_id = {r["recipient_id"]: r for r in store.recipients()}
    assert by_id["alice"]["revoked"] is False
    assert by_id["malory"]["revoked"] is True


def test_a_later_certificate_refreshes_the_row_without_touching_revoked(tmp_path):
    """Re-enrolment updates the keys and leaves the flag where it is.

    Both directions matter. A new certificate must not clear a revocation
    (tested above) and it must not impose one either -- if an operator revokes
    someone, re-issuing the certificate is not a reinstatement, and reinstating
    is a separate, deliberate act.
    """
    ca = CA.create()
    store = Store.open(str(tmp_path / "store.db"))
    first = _cert(ca, "bob")
    store.add_recipient(first)

    second = _cert(ca, "bob")
    assert second.serial != first.serial
    store.add_recipient(second)

    assert store.get_cert("bob").serial == second.serial, (
        "the new certificate was not taken up")
    assert store.is_revoked("bob") is False

    store.revoke("bob")
    third = _cert(ca, "bob")
    store.add_recipient(third)
    assert store.is_revoked("bob") is True, (
        "re-issuing a certificate while someone was revoked reinstated them")
    assert store.get_cert("bob").serial == third.serial


def test_reinstate_undoes_a_revocation_and_reports_whether_it_did(tmp_path):
    ca = CA.create()
    store = Store.open(str(tmp_path / "store.db"))
    store.add_recipient(_cert(ca, "dave"))

    store.revoke("dave")
    assert store.is_revoked("dave") is True
    assert store.reinstate("dave") is True
    assert store.is_revoked("dave") is False
    # Idempotent: reinstating someone who is not revoked changes no row, which
    # is how the route tells "no such recipient" from "already fine" -- both
    # would otherwise return success.
    assert store.reinstate("dave") is True, (
        "UPDATE ... SET revoked=0 matches the row even when it is already 0; "
        "rowcount counts matched rows, so this stays True")


def test_revoke_and_reinstate_report_an_unknown_recipient(tmp_path):
    """A 404 rather than a success that changed nothing.

    ``rowcount`` is the whole reason these return a bool. An operator who
    mistypes a name must not be told the revocation worked.
    """
    store = Store.open(str(tmp_path / "store.db"))
    assert store.revoke("nobody") is False
    assert store.reinstate("nobody") is False


def test_an_unknown_recipient_is_revoked_by_default(tmp_path):
    """Default-deny, and it is the same answer as an explicit revocation.

    ``is_revoked`` returning True for an unknown name means a caller that
    forgets to check existence still refuses rather than admits.
    """
    store = Store.open(str(tmp_path / "store.db"))
    assert store.is_revoked("ghost") is True


# ==========================================================================
# The migration
# ==========================================================================

# The `sessions` table exactly as the version before device_fp created it.
_OLD_SESSIONS = """
CREATE TABLE sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    ledger_index INTEGER,
    leaf_hash TEXT,
    watermark_seed TEXT,
    released INTEGER NOT NULL DEFAULT 0,
    source_ip TEXT,
    ts TEXT NOT NULL
);
"""


def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_an_existing_database_gains_the_device_fingerprint_column(tmp_path):
    """The upgrade path, replayed rather than assumed.

    ``CREATE TABLE IF NOT EXISTS`` does nothing to a table that already exists,
    so a ``store.db`` left over from an earlier run would keep the old shape and
    the first ``record_session`` would fail with "table sessions has no column
    named device_fp" -- a message about the schema standing in for the real
    problem. The migration is what makes an existing deployment work.
    """
    path = str(tmp_path / "store.db")
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_SESSIONS)
    # A row written by the old version, which the migration must not disturb.
    conn.execute("INSERT INTO sessions (doc_id, recipient_id, ledger_index,"
                 " leaf_hash, watermark_seed, released, source_ip, ts)"
                 " VALUES ('DOC-0000','alice',0,'ab','cd',1,'127.0.0.1','t')")
    conn.commit()
    assert "device_fp" not in _columns(conn, "sessions")
    conn.close()

    store = Store.open(path)
    assert "device_fp" in _columns(store.conn, "sessions")

    rows = store.sessions()
    assert len(rows) == 1, "the migration lost the existing session rows"
    assert rows[0]["device_fp"] is None, (
        "a row predating the column has no fingerprint, and NULL is the honest "
        "value -- inventing one would make an unrecorded open look recorded")

    # And the column is usable, which is the point of adding it.
    store.record_session("DOC-0000", "alice", 1, "ef", "12", True,
                         device_fp="sha256:abc")
    assert store.sessions()[0]["device_fp"] == "sha256:abc"


def test_the_migration_is_idempotent(tmp_path):
    """Opening the same database twice must not try to add the column twice.

    ``ALTER TABLE ADD COLUMN`` on an existing column is an error, so a migration
    that is not guarded would fail on the second start -- which is every start
    after the first.
    """
    path = str(tmp_path / "store.db")
    Store.open(path).conn.close()
    for _ in range(3):
        store = Store.open(path)
        assert "device_fp" in _columns(store.conn, "sessions")
        store.conn.close()


def test_opening_a_fresh_database_creates_the_column_directly(tmp_path):
    """No migration needed on a new file; the schema carries it."""
    store = Store.open(str(tmp_path / "fresh.db"))
    assert "device_fp" in _columns(store.conn, "sessions")


# ==========================================================================
# The two counts the admin screen renders
# ==========================================================================

def test_the_register_counts_grants_and_opens_per_recipient(tmp_path):
    """Two numbers, counted in SQL rather than by moving the tables.

    The screen asks "how many documents is this person granted, and how many
    times have they opened one". Answering that in the browser would mean
    shipping every grant and every session row for every recipient to render
    one number per row.
    """
    ca = CA.create()
    store = Store.open(str(tmp_path / "store.db"))
    for rid in ("alice", "bob"):
        store.add_recipient(_cert(ca, rid))

    for i in range(2):
        store.add_document(
            {"doc_id": f"DOC-000{i}", "classification": "internal",
             "doc_hash": "00" * 32, "cipher": "AES-256-GCM"},
            ["alice", "bob"])
    store.add_document(
        {"doc_id": "DOC-0002", "classification": "internal",
         "doc_hash": "11" * 32, "cipher": "AES-256-GCM"}, ["alice"])

    assert store.grants_count("alice") == 3
    assert store.grants_count("bob") == 2
    assert store.grants_count("carol") == 0

    store.record_session("DOC-0000", "alice", 0, "aa", "bb", True,
                         device_fp="sha256:one")
    store.record_session("DOC-0001", "alice", 1, "cc", "dd", True,
                         device_fp="sha256:two")

    assert len(store.sessions_for("alice")) == 2
    assert store.sessions_for("bob") == []
    # Most recent first: the register shows the *last* device asserted, and
    # "last" has to mean last.
    assert store.sessions_for("alice")[0]["device_fp"] == "sha256:two"
