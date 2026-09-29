"""The transparency log: append-only leaves, Signed Tree Heads, fail-closed.

The invariant this file exists to enforce:

    **Nothing key-related is released unless the request that asked for it is
    already committed, with a witness quorum, to the log.**

That ordering is not a convention observed by callers -- it is structural. The
authority cannot obtain a content key except through
``gated_append_for_decryption``, which performs the append and the quorum
gathering *before* it returns anything, and which raises (having rolled back)
if either fails. There is no "append later" path and no best-effort mode.

Atomicity note: the witness quorum is gathered over the network while a SQLite
write transaction is open, which is normally something to avoid. It is done here
deliberately, because the alternative -- commit the leaf, then gather signatures,
then repair on failure -- has a window in which a committed leaf has no valid
STH, and a committed-but-unwitnessed leaf is precisely what the whole design is
trying to make impossible. Appends are serialised by ``_lock`` so the held
transaction blocks no other writer; this is a single-writer log by construction.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from ..crypto import pqc
from ..crypto.kdf import watermark_seed
from ..models import STH, canon
from . import merkle
from .witnesses import QuorumNotMet, WitnessQuorum


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS leaves (
    idx INTEGER PRIMARY KEY,
    leaf_data BLOB NOT NULL,
    leaf_hash BLOB NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sth (
    tree_size INTEGER PRIMARY KEY,
    root_hash BLOB NOT NULL,
    ts TEXT NOT NULL,
    log_sig BLOB NOT NULL,
    witness_sigs TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class STHNotWitnessed(Exception):
    """The log refused to publish an STH. Nothing was committed."""


class LedgerLog:
    def __init__(self, conn: sqlite3.Connection, log_pub: bytes, log_sec: bytes,
                 quorum: WitnessQuorum):
        self.conn = conn
        self.log_pub = log_pub
        self.log_sec = log_sec
        self.quorum = quorum
        self._lock = threading.Lock()
        self._hashes: list[bytes] = []
        self._reload_cache()

    # -- construction ------------------------------------------------------

    @classmethod
    def open(cls, path: str, quorum: WitnessQuorum,
             check_same_thread: bool = True) -> "LedgerLog":
        conn = sqlite3.connect(path, check_same_thread=check_same_thread)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        row = conn.execute("SELECT value FROM meta WHERE key='log_pub'").fetchone()
        if row is None:
            log_pub, log_sec = pqc.sig_keypair(pqc.SIG)
            conn.execute("INSERT INTO meta VALUES ('log_pub', ?)",
                         (log_pub.hex(),))
            # Demo-only: the log's private key sits in the same database it
            # signs. A real deployment keeps this in an HSM and the operator
            # cannot read it. See README "What is simulated".
            conn.execute("INSERT INTO meta VALUES ('log_sec', ?)",
                         (log_sec.hex(),))
            conn.commit()
        else:
            log_pub = bytes.fromhex(row["value"])
            log_sec = bytes.fromhex(conn.execute(
                "SELECT value FROM meta WHERE key='log_sec'").fetchone()["value"])
        return cls(conn, log_pub, log_sec, quorum)

    def _reload_cache(self) -> None:
        self._hashes = [bytes(r["leaf_hash"]) for r in self.conn.execute(
            "SELECT leaf_hash FROM leaves ORDER BY idx")]

    # -- reads -------------------------------------------------------------

    def tree_size(self) -> int:
        return len(self._hashes)

    def current_root(self) -> bytes:
        return merkle.root_from_hashes(self._hashes)

    def leaf_hashes(self) -> list[bytes]:
        return list(self._hashes)

    def get_leaf(self, idx: int) -> bytes:
        row = self.conn.execute("SELECT leaf_data FROM leaves WHERE idx=?",
                                (idx,)).fetchone()
        if row is None:
            raise IndexError(f"no leaf at index {idx}")
        return bytes(row["leaf_data"])

    def inclusion_proof(self, idx: int) -> list[bytes]:
        return merkle.inclusion_proof(self._hashes, idx)

    def consistency_proof(self, m: int, n: int | None = None) -> list[bytes]:
        n = self.tree_size() if n is None else n
        return merkle.consistency_proof(self._hashes[:n], m, n)

    def latest_sth(self) -> STH | None:
        row = self.conn.execute(
            "SELECT * FROM sth ORDER BY tree_size DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return STH(tree_size=row["tree_size"],
                   root_hash=bytes(row["root_hash"]).hex(),
                   timestamp=row["ts"],
                   log_sig=bytes(row["log_sig"]).hex(),
                   witness_sigs=json.loads(row["witness_sigs"]))

    def sth_at(self, tree_size: int) -> STH | None:
        row = self.conn.execute("SELECT * FROM sth WHERE tree_size=?",
                                (tree_size,)).fetchone()
        if row is None:
            return None
        return STH(tree_size=row["tree_size"],
                   root_hash=bytes(row["root_hash"]).hex(),
                   timestamp=row["ts"],
                   log_sig=bytes(row["log_sig"]).hex(),
                   witness_sigs=json.loads(row["witness_sigs"]))

    # -- the append --------------------------------------------------------

    def append(self, leaf_data: bytes) -> tuple[int, list[bytes], STH, list[dict]]:
        """Commit one leaf and publish a witnessed STH for the new tree.

        Returns ``(index, inclusion_proof, sth, witness_refusals)``.

        Raises :class:`STHNotWitnessed` (having rolled back) if the quorum is
        not reached. On that path the leaf is *not* in the log and the caller
        must not proceed.
        """
        with self._lock:
            idx = len(self._hashes)
            lh = merkle.leaf_hash(leaf_data)
            new_hashes = self._hashes + [lh]
            root = merkle.root_from_hashes(new_hashes)
            tree_size = len(new_hashes)
            sth = STH(tree_size=tree_size, root_hash=root.hex(),
                      timestamp=_now())

            self.conn.execute("BEGIN IMMEDIATE")
            try:
                # The STH's own signature goes on before the witnesses see it,
                # so a witness is attesting to the log's claim, not just to a
                # root hash someone handed it.
                sth.log_sig = pqc.sign(self.log_sec, sth.tbs(), pqc.SIG).hex()

                # Network round trips happen here, inside the transaction, on
                # purpose -- see the module docstring.
                sth.witness_sigs, refusals = self.quorum.collect(
                    tree_size, sth.root_hash, sth.timestamp, new_hashes)

                self.conn.execute(
                    "INSERT INTO leaves VALUES (?,?,?,?)",
                    (idx, leaf_data, lh, sth.timestamp))
                self.conn.execute(
                    "INSERT INTO sth VALUES (?,?,?,?,?)",
                    (sth.tree_size, root, sth.timestamp,
                     bytes.fromhex(sth.log_sig), json.dumps(sth.witness_sigs)))
            except QuorumNotMet as e:
                self.conn.rollback()
                # The invariant statement goes first, because that is what the
                # caller has to act on, and it is what the API returns to the
                # client. The underlying reason is appended rather than
                # discarded: on this path the refusal detail -- which witness
                # was unreachable, how many co-signed -- exists nowhere else, so
                # dropping it would leave an operator unable to find out why a
                # release was refused. It is chained rather than replaced for
                # the same reason.
                raise STHNotWitnessed(
                    "witness quorum not met; no leaf committed and no key may "
                    f"be released ({e})") from e
            except Exception:
                self.conn.rollback()
                raise
            self.conn.commit()
            self._hashes = new_hashes
            return idx, merkle.inclusion_proof(self._hashes, idx), sth, refusals

    def gated_append_for_decryption(self, dr_leaf_bytes: bytes,
                                    source_ip: str | None = None) -> dict:
        """The only path to a content key.

        ``source_ip`` is recorded because the authority is network-facing: the
        ledger entry should say where the request came from, not only who signed
        it. It is metadata for the investigation, never evidence on its own --
        it is unauthenticated and trivially spoofable, and the demo says so.
        """
        wrapper = {"kind": "decryption-request",
                   "request": json.loads(dr_leaf_bytes.decode("utf-8")),
                   "source_ip": source_ip}
        idx, proof, sth, refusals = self.append(canon(wrapper))
        return {
            "index": idx,
            "leaf_hash": merkle.leaf_hash(canon(wrapper)).hex(),
            "inclusion_proof": [p.hex() for p in proof],
            "sth": sth,
            "witness_refusals": refusals,
            # Bound to the committed entry, so two opens by the same recipient
            # of the same document carry different marks.
            "watermark_seed": watermark_seed(merkle.leaf_hash(canon(wrapper))).hex(),
        }

    def append_event(self, obj) -> dict:
        """Append a non-decryption leaf (device enrolment, access event, ...)."""
        leaf = obj.leaf_bytes() if hasattr(obj, "leaf_bytes") else canon(obj)
        idx, proof, sth, refusals = self.append(leaf)
        return {"index": idx, "leaf_hash": merkle.leaf_hash(leaf).hex(),
                "inclusion_proof": [p.hex() for p in proof], "sth": sth,
                "witness_refusals": refusals}
