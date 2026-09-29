"""Authority-side metadata storage.

Deliberately separate from the ledger database. The ledger is the evidence: it
is append-only, hash-linked and witnessed, and nothing here may ever be mistaken
for it. This database is ordinary mutable operational state -- which recipients
exist, which documents were distributed, whether a recipient has been revoked.
It can be edited by the operator, and that is fine, because **nothing in the
attribution path trusts it**. An investigator resolving a leak reads the ledger,
not these tables.

The distinction is the point of the whole design, so it is worth being concrete:
if an operator deleted every row in this database, a leak investigation would
still work -- the ledger entry carries the signed request, and the certificate
and public keys can be re-derived. If an operator edited this database to frame
someone, the attribution would still name whoever's key actually signed, because
the signature is checked against the certificate, not against a stored name.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..crypto import ca as ca_mod
from ..models import Certificate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS recipients (
    recipient_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    cert_json TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    classification TEXT NOT NULL,
    doc_hash TEXT NOT NULL,
    package_json TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grants (
    doc_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    created TEXT NOT NULL,
    PRIMARY KEY (doc_id, recipient_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    ledger_index INTEGER,
    leaf_hash TEXT,
    watermark_seed TEXT,
    released INTEGER NOT NULL DEFAULT 0,
    source_ip TEXT,
    device_fp TEXT,
    ts TEXT NOT NULL
);
"""


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add a column a later version introduced to an existing database.

        Every statement in ``_SCHEMA`` is ``CREATE TABLE IF NOT EXISTS``, so a
        ``store.db`` written by an earlier version keeps the shape it was
        created with and never gains a new column. Without this step, a new
        build run against an old deployment fails at INSERT time with "table
        sessions has no column named device_fp" -- a message about the schema
        standing in for the real problem, which is that nobody migrated it.
        """
        cols = {r["name"]
                for r in self.conn.execute("PRAGMA table_info(sessions)")}
        if "device_fp" not in cols:
            self.conn.execute("ALTER TABLE sessions ADD COLUMN device_fp TEXT")
            self.conn.commit()

    @classmethod
    def open(cls, path: str, check_same_thread: bool = True) -> "Store":
        conn = sqlite3.connect(path, check_same_thread=check_same_thread)
        conn.execute("PRAGMA journal_mode=WAL")
        return cls(conn)

    # -- recipients --------------------------------------------------------

    def add_recipient(self, cert: Certificate) -> None:
        """Insert a recipient, or refresh the certificate of one already known.

        An upsert that deliberately does not touch ``revoked``. The obvious
        spelling here is ``INSERT OR REPLACE``, and it has a consequence that
        matters: ``Deployment.sync_store`` re-adds every recipient from the CA's
        file on every startup, so REPLACE would rewrite ``revoked`` from the
        certificate's role each run -- and a revocation would quietly undo
        itself the next time the demo was restarted. A revocation that does not
        survive a restart is not a revocation.

        A recipient being inserted for the first time still gets ``revoked`` from
        their role, which is where it has always come from.
        """
        self.conn.execute(
            "INSERT INTO recipients (recipient_id, role, cert_json, revoked,"
            " created) VALUES (?,?,?,?,?)"
            " ON CONFLICT(recipient_id) DO UPDATE SET"
            " role=excluded.role, cert_json=excluded.cert_json",
            (cert.recipient_id, cert.role, json.dumps(cert.__dict__),
             int(cert.role == "revoked"), _now()))
        self.conn.commit()

    def get_cert(self, recipient_id: str) -> Certificate | None:
        row = self.conn.execute(
            "SELECT cert_json FROM recipients WHERE recipient_id=?",
            (recipient_id,)).fetchone()
        if row is None:
            return None
        return Certificate(**json.loads(row["cert_json"]))

    def is_revoked(self, recipient_id: str) -> bool:
        row = self.conn.execute(
            "SELECT revoked FROM recipients WHERE recipient_id=?",
            (recipient_id,)).fetchone()
        return bool(row["revoked"]) if row else True  # unknown == revoked

    def revoke(self, recipient_id: str) -> bool:
        """Mark a recipient revoked. Returns whether a row changed.

        The return value is what lets a caller turn "no such recipient" into a
        404 instead of a success that revoked nobody.
        """
        cur = self.conn.execute(
            "UPDATE recipients SET revoked=1 WHERE recipient_id=?",
            (recipient_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def reinstate(self, recipient_id: str) -> bool:
        """Clear a revocation, the inverse of :meth:`revoke`.

        Revocation is one row's flag, so undoing it is a flag write and nothing
        more: the certificate was never withdrawn, and no key was ever
        destroyed. Whoever held that identity's private key holds it still.
        """
        cur = self.conn.execute(
            "UPDATE recipients SET revoked=0 WHERE recipient_id=?",
            (recipient_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def recipients(self) -> list[dict]:
        return [{"recipient_id": r["recipient_id"], "role": r["role"],
                 "revoked": bool(r["revoked"])}
                for r in self.conn.execute(
                    "SELECT * FROM recipients ORDER BY recipient_id")]

    # -- documents ---------------------------------------------------------

    def add_document(self, package: dict, recipients: list[str]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
            (package["doc_id"], package["classification"], package["doc_hash"],
             json.dumps(package), _now()))
        for rid in recipients:
            self.conn.execute("INSERT OR IGNORE INTO grants VALUES (?,?,?)",
                              (package["doc_id"], rid, _now()))
        self.conn.commit()

    def get_document(self, doc_id: str) -> dict | None:
        row = self.conn.execute("SELECT package_json FROM documents WHERE doc_id=?",
                                (doc_id,)).fetchone()
        return json.loads(row["package_json"]) if row else None

    def documents(self) -> list[dict]:
        return [{"doc_id": r["doc_id"], "classification": r["classification"],
                 "doc_hash": r["doc_hash"]}
                for r in self.conn.execute(
                    "SELECT * FROM documents ORDER BY doc_id")]

    def is_authorized(self, doc_id: str, recipient_id: str) -> bool:
        """Whether this recipient was granted this document.

        Default-deny: an unknown pair is not authorized. A recipient who somehow
        holds a valid certificate still cannot open a document that was never
        distributed to them.
        """
        row = self.conn.execute(
            "SELECT 1 FROM grants WHERE doc_id=? AND recipient_id=?",
            (doc_id, recipient_id)).fetchone()
        return row is not None

    def grants_for(self, doc_id: str) -> list[str]:
        return [r["recipient_id"] for r in self.conn.execute(
            "SELECT recipient_id FROM grants WHERE doc_id=? ORDER BY recipient_id",
            (doc_id,))]

    # -- sessions ----------------------------------------------------------

    def record_session(self, doc_id: str, recipient_id: str, ledger_index: int,
                       leaf_hash: str, seed: str, released: bool,
                       source_ip: str | None = None,
                       device_fp: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions (doc_id, recipient_id, ledger_index, leaf_hash,"
            " watermark_seed, released, source_ip, device_fp, ts)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (doc_id, recipient_id, ledger_index, leaf_hash, seed,
             int(released), source_ip, device_fp, _now()))
        self.conn.commit()
        return cur.lastrowid

    def sessions(self, doc_id: str | None = None) -> list[dict]:
        if doc_id:
            rows = self.conn.execute(
                "SELECT * FROM sessions WHERE doc_id=? ORDER BY session_id DESC",
                (doc_id,))
        else:
            rows = self.conn.execute("SELECT * FROM sessions ORDER BY session_id DESC")
        return [dict(r) for r in rows]

    # -- the admin view's two questions ------------------------------------
    #
    # Deliberately counts rather than lists. The admin screen asks "how many
    # documents is this person granted, and how many times have they opened
    # one", and answering that by listing every grant and every session for
    # every recipient would move the whole operational database into the
    # browser to render seven numbers.

    def grants_count(self, recipient_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM grants WHERE recipient_id=?",
            (recipient_id,)).fetchone()
        return int(row["n"])

    def sessions_for(self, recipient_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM sessions WHERE recipient_id=? ORDER BY session_id DESC",
            (recipient_id,))]
