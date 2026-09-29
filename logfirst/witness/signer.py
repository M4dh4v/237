"""Witness node logic: what a witness signs, and what it refuses to sign.

A witness that signs whatever it is handed is decoration. The value of a
witness comes entirely from what it *declines* to sign, so the refusal rules are
the substance of this module and are worth stating plainly.

A witness keeps an append-only record of every STH it has co-signed. When asked
to co-sign a new STH it applies three rules:

**Rule 1 -- never contradict yourself.** If it already signed a different root
at the same tree size, it refuses. This is the equivocation guard, and it is the
one that matters: an operator running a split view must show root A to one
witness and root B to another. Under this rule the second witness refuses, and
if both were somehow to sign, the two signatures are themselves proof of
misbehaviour.

**Rule 2 -- never go backwards.** If the new tree size is smaller than the
largest it has signed, it refuses. An append-only log has no legitimate reason
to shrink; a smaller head is either a rollback attack or a server that has lost
data, and both should stop the release rather than silently produce a key.

**Rule 3 -- prove the extension.** For a strictly larger tree, the witness
demands a consistency proof from *the root it last signed* to the new root, and
verifies it itself before signing. This is what stops a server from presenting
an unrelated history as an extension of the one the witness already attested to.
Without this rule a witness only attests "some tree existed", which is close to
useless; with it, the witness attests "this tree contains everything I have
previously seen, unchanged".

The witness does not need to trust the server for any of this. Rules 1 and 2 use
only its own stored state; rule 3 is checked with pure Merkle arithmetic against
that same state.
"""

from __future__ import annotations

import json
import os

from ..crypto import pqc
from ..ledger import merkle
from ..models import STH, canon


class CosignRefused(Exception):
    """Raised instead of producing a signature. Never caught into a fallback."""


class WitnessSigner:
    """Holds one witness's key and its record of what it has signed."""

    def __init__(self, witness_id: str, sig_pub: bytes, sig_sec: bytes,
                 state_path: str | None = None):
        self.witness_id = witness_id
        self.sig_pub = sig_pub
        self.sig_sec = sig_sec
        self.state_path = state_path
        # tree_size -> {"root_hash": hex, "sig": hex, "timestamp": iso}
        self.signed: dict[int, dict] = {}
        if state_path and os.path.exists(state_path):
            self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        with open(self.state_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.signed = {int(k): v for k, v in raw.get("signed", {}).items()}

    def _save(self) -> None:
        if not self.state_path:
            return
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            # The private key is written here because this is a self-contained
            # demo. A real witness keeps it in an HSM or at least a 0600 file
            # owned by a service account; README says so. Persisting it is not
            # optional though -- losing it on restart would make the witness
            # look like a brand-new identity, silently discarding the record of
            # what it had already signed and with it the equivocation and
            # rollback rules that depend on that history.
            json.dump({"witness_id": self.witness_id,
                       "pub": self.sig_pub.hex(),
                       "sec": self.sig_sec.hex(),
                       "signed": {str(k): v for k, v in self.signed.items()}},
                      f, indent=1, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.state_path)

    @classmethod
    def create(cls, witness_id: str, state_path: str | None = None) -> "WitnessSigner":
        pub, sec = pqc.sig_keypair(pqc.SIG)
        w = cls(witness_id, pub, sec, state_path)
        w._save()
        return w

    @classmethod
    def open(cls, witness_id: str, state_path: str) -> "WitnessSigner":
        """Load a witness from disk, generating its key on first use."""
        if os.path.exists(state_path):
            with open(state_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return cls(witness_id, bytes.fromhex(raw["pub"]),
                       bytes.fromhex(raw["sec"]), state_path)
        return cls.create(witness_id, state_path)

    # -- the interesting part ---------------------------------------------

    @property
    def max_size(self) -> int:
        return max(self.signed) if self.signed else 0

    @property
    def last_root(self) -> bytes | None:
        if not self.signed:
            return None
        return bytes.fromhex(self.signed[self.max_size]["root_hash"])

    def cosign(self, tree_size: int, root_hash: str, timestamp: str,
               consistency_proof: list[str] | None = None) -> dict:
        """Apply the three rules, then sign. Raises ``CosignRefused`` otherwise.

        ``timestamp`` is the *log's* timestamp for this head, and it has to be
        passed in rather than stamped here. A witness signs the same
        ``STH.tbs()`` the log signed -- ``{tree_size, root_hash, timestamp}`` --
        so if it substituted its own clock reading, the two signatures would be
        over different messages and no verifier could ever check the
        co-signature against the published head. The witness would be attesting
        to something nobody else can see. Taking the log's value means a
        witness's signature is checkable by anyone holding the STH, which is the
        entire point of having witnesses.

        Returns ``{"witness_id", "sig", "tree_size", "root_hash",
        "already_signed"}``. Idempotent: asking twice for the same head returns
        the same signature rather than an error, because a retried request after
        a dropped response must not look like an attack.
        """
        root = bytes.fromhex(root_hash)

        # Rule 1: same size, same root -> already signed; same size, different
        # root -> equivocation, refuse and say so loudly.
        prior = self.signed.get(tree_size)
        if prior is not None:
            if prior["root_hash"] == root_hash:
                return {"witness_id": self.witness_id, "sig": prior["sig"],
                        "tree_size": tree_size, "root_hash": root_hash,
                        "already_signed": True}
            raise CosignRefused(
                f"EQUIVOCATION: already signed size {tree_size} with root "
                f"{prior['root_hash'][:16]}..., now offered {root_hash[:16]}...")

        # Rule 2: no shrinking.
        if tree_size < self.max_size:
            raise CosignRefused(
                f"ROLLBACK: size {tree_size} is behind my last signed size "
                f"{self.max_size}")

        # Rule 3: an extension must be proven against my own last root.
        if self.signed:
            old_size = self.max_size
            old_root = self.last_root
            if not consistency_proof:
                raise CosignRefused(
                    f"NO PROOF: size {tree_size} extends {old_size} but no "
                    "consistency proof was supplied")
            proof = [bytes.fromhex(p) for p in consistency_proof]
            if not merkle.verify_consistency(old_size, tree_size, old_root,
                                             root, proof):
                raise CosignRefused(
                    f"BAD PROOF: the offered tree of size {tree_size} is not a "
                    f"consistent extension of size {old_size} that I signed")

        sth = STH(tree_size=tree_size, root_hash=root_hash, timestamp=timestamp)
        sig = pqc.sign(self.sig_sec, sth.tbs(), pqc.SIG).hex()
        self.signed[tree_size] = {"root_hash": root_hash, "sig": sig,
                                  "timestamp": timestamp}
        self._save()
        return {"witness_id": self.witness_id, "sig": sig,
                "tree_size": tree_size, "root_hash": root_hash,
                "already_signed": False}

    def verify_signature(self, sth: STH) -> bool:
        sig = sth.witness_sigs.get(self.witness_id)
        return bool(sig) and pqc.verify(self.sig_pub, sth.tbs(),
                                        bytes.fromhex(sig))

    def history(self) -> dict:
        return {"witness_id": self.witness_id, "pub": self.sig_pub.hex(),
                "max_size": self.max_size,
                "signed": {str(k): v["root_hash"] for k, v in
                           sorted(self.signed.items())}}
