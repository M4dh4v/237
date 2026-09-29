"""Shared fixtures.

The witness nodes run as real HTTP processes in the demo and in
``tests/test_authority_http.py``. Spawning three subprocesses for every test
that needs a ledger would make the suite slow and flaky for no gain, so
:class:`InProcessWitness` presents a :class:`~logfirst.witness.signer.WitnessSigner`
through the same interface :class:`~logfirst.ledger.witnesses.WitnessClient`
exposes. The quorum logic under test is identical either way; what the socket
would add -- serialisation and HTTP status mapping -- is covered by the
end-to-end test that does use real processes.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from logfirst.crypto import pqc
from logfirst.ledger.log import LedgerLog
from logfirst.ledger.witnesses import (
    QuorumNotMet, WitnessQuorum, WitnessUnavailable,
)
from logfirst.models import DecryptionRequest
from logfirst.witness.signer import CosignRefused, WitnessSigner


class InProcessWitness:
    """A witness with no socket in front of it."""

    def __init__(self, signer: WitnessSigner):
        self.signer = signer

    @property
    def witness_id(self) -> str:
        return self.signer.witness_id

    def info(self) -> dict:
        return {"witness_id": self.witness_id, "pub": self.signer.sig_pub.hex()}

    def max_size(self) -> int:
        return self.signer.max_size

    def cosign(self, tree_size: int, root_hash: str, timestamp: str,
               consistency_proof: list[str], note: str | None = None) -> dict:
        try:
            return self.signer.cosign(tree_size, root_hash, timestamp,
                                      consistency_proof)
        except CosignRefused as e:
            # The real client maps a 409 to WitnessUnavailable; mirror that so
            # the quorum sees refusals exactly as it would over HTTP.
            raise WitnessUnavailable(f"{self.witness_id} refused: {e}") from e


class DeadWitness:
    """A witness that is simply down. Exercises the unreachable path."""

    def __init__(self, witness_id: str):
        self.witness_id = witness_id

    def info(self):
        raise WitnessUnavailable(f"{self.witness_id}: connection refused")

    def max_size(self):
        raise WitnessUnavailable(f"{self.witness_id}: connection refused")

    def cosign(self, *a, **kw):
        raise WitnessUnavailable(f"{self.witness_id}: connection refused")


def make_witnesses(tmp_path, n: int = 3,
                   stateful: bool = True) -> list[InProcessWitness]:
    """``n`` witnesses. With ``stateful=False`` they keep no history on disk."""
    out = []
    for i in range(1, n + 1):
        wid = f"w{i}"
        if stateful:
            w = WitnessSigner.open(wid, str(tmp_path / f"{wid}.json"))
        else:
            pub, sec = pqc.sig_keypair(pqc.SIG)
            w = WitnessSigner(wid, pub, sec, None)
        out.append(InProcessWitness(w))
    return out


def make_log(tmp_path, witnesses, min_witnesses: int = 2,
             name: str = "ledger.db") -> LedgerLog:
    quorum = WitnessQuorum(list(witnesses), min_witnesses=min_witnesses)
    return LedgerLog.open(str(tmp_path / name), quorum)


def make_request(recipient_id: str = "alice", doc_id: str = "DOC-0000",
                 sig_sec: bytes | None = None, **over) -> DecryptionRequest:
    """A properly signed decryption request, as a real client would build it."""
    if sig_sec is None:
        _, sig_sec = pqc.sig_keypair(pqc.SIG)
    kem_pub, _ = pqc.kem_keypair(pqc.KEM)
    dr = DecryptionRequest(
        doc_id=doc_id, recipient_id=recipient_id, nonce="ab" * 16,
        timestamp="2026-01-01T00:00:00+00:00", device_fp="cd" * 32,
        ephemeral_kem_pub=kem_pub.hex())
    for k, v in over.items():
        setattr(dr, k, v)
    dr.sig = pqc.sign(sig_sec, dr.tbs(), pqc.SIG).hex()
    return dr


@pytest.fixture
def witnesses(tmp_path):
    return make_witnesses(tmp_path, 3)


@pytest.fixture
def log(tmp_path, witnesses):
    return make_log(tmp_path, witnesses, min_witnesses=2)


@pytest.fixture
def recipient_key():
    """One recipient's ML-DSA keypair, generated once per test that needs it."""
    pub, sec = pqc.sig_keypair(pqc.SIG)
    return {"recipient_id": "alice", "pub": pub, "sec": sec}
