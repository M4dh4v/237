"""Reaching the witness nodes, and enforcing the quorum.

Two details here are easy to get subtly wrong, and both matter.

**Each witness needs its own proof.** Witnesses fall behind independently: one
may have co-signed every head, another may have missed a few while it was
restarted. Rule 3 in ``witness/signer.py`` demands a consistency proof from *the
root that witness last signed*, so the authority must ask each witness where it
is and compute a proof from that size -- not send one universal proof from the
previous STH. Sending the wrong proof is a refusal, not a corruption, which is
the safe direction, but it means a naive implementation silently degrades to
"quorum never met" the first time a witness restarts.

**Quorum failure is a hard stop.** :meth:`WitnessQuorum.collect` raises rather
than returning a partial set, and the authority treats that exception as "release
nothing". There is no code path that logs a key release because it *nearly* had
a quorum.
"""

from __future__ import annotations

import httpx

from . import merkle


class WitnessUnavailable(Exception):
    """A witness could not be reached or answered unusably."""


class QuorumNotMet(Exception):
    """Fewer than ``min_witnesses`` co-signed. Callers must release nothing."""


class WitnessClient:
    """HTTP client for one witness process."""

    def __init__(self, witness_id: str, base_url: str, timeout: float = 5.0):
        self.witness_id = witness_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def info(self) -> dict:
        try:
            r = httpx.get(f"{self.base_url}/pubkey", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            raise WitnessUnavailable(f"{self.witness_id}: {e}") from e

    def max_size(self) -> int:
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=self.timeout)
            r.raise_for_status()
            return int(r.json()["max_size"])
        except Exception as e:
            raise WitnessUnavailable(f"{self.witness_id}: {e}") from e

    def cosign(self, tree_size: int, root_hash: str, timestamp: str,
               consistency_proof: list[str], note: str | None = None) -> dict:
        """Ask for a co-signature. Refusals surface as ``WitnessUnavailable``."""
        try:
            r = httpx.post(f"{self.base_url}/cosign",
                           json={"tree_size": tree_size, "root_hash": root_hash,
                                 "timestamp": timestamp,
                                 "consistency_proof": consistency_proof,
                                 "note": note},
                           timeout=self.timeout)
        except Exception as e:
            raise WitnessUnavailable(f"{self.witness_id}: {e}") from e
        if r.status_code == 409:
            raise WitnessUnavailable(
                f"{self.witness_id} refused: {r.json().get('detail', '')}")
        try:
            r.raise_for_status()
        except Exception as e:
            raise WitnessUnavailable(f"{self.witness_id}: {e}") from e
        return r.json()


class WitnessQuorum:
    """A set of witnesses and the minimum that must co-sign."""

    def __init__(self, clients: list[WitnessClient], min_witnesses: int = 2):
        if min_witnesses < 1:
            raise ValueError("min_witnesses must be at least 1")
        if min_witnesses > len(clients):
            # Refuse to construct an unsatisfiable quorum: this is the
            # configuration error that would otherwise show up as a mysterious
            # runtime failure on the first release, with the document already
            # encrypted and no way to open it.
            raise ValueError(
                f"min_witnesses={min_witnesses} exceeds the {len(clients)} "
                "witnesses configured")
        self.clients = clients
        self.min_witnesses = min_witnesses

    def witness_ids(self) -> list[str]:
        return [c.witness_id for c in self.clients]

    def public_keys(self) -> dict[str, str]:
        """``{witness_id: hex pubkey}``, for publishing alongside the ledger."""
        out = {}
        for c in self.clients:
            out[c.witness_id] = c.info()["pub"]
        return out

    def collect(self, tree_size: int, root_hash: str, timestamp: str,
                leaf_hashes: list[bytes],
                note: str | None = None) -> tuple[dict[str, str], list[dict]]:
        """Gather co-signatures. Returns ``({witness_id: sig}, refusals)``.

        ``timestamp`` is the log's own timestamp for this head and is passed
        straight through to each witness, so every party signs the identical
        ``STH.tbs()``. See :meth:`WitnessSigner.cosign` for why that matters.

        ``leaf_hashes`` is the log's full leaf-hash list, needed to compute each
        witness a consistency proof from wherever that witness actually is.

        Raises :class:`QuorumNotMet` if fewer than ``min_witnesses`` signed --
        including when some witnesses were simply unreachable. A witness that is
        down reduces the quorum; it does not lower the bar.
        """
        sigs: dict[str, str] = {}
        refusals: list[dict] = []
        for client in self.clients:
            try:
                old_size = client.max_size()
                if old_size and old_size < tree_size:
                    proof = [p.hex() for p in
                             merkle.consistency_proof(leaf_hashes[:tree_size],
                                                      old_size, tree_size)]
                else:
                    proof = []
                res = client.cosign(tree_size, root_hash, timestamp, proof,
                                    note=note)
            except WitnessUnavailable as e:
                refusals.append({"witness_id": client.witness_id,
                                 "reason": str(e)})
                continue
            sigs[res["witness_id"]] = res["sig"]

        if len(sigs) < self.min_witnesses:
            raise QuorumNotMet(
                f"{len(sigs)}/{self.min_witnesses} witnesses co-signed "
                f"({len(refusals)} refused or unreachable): "
                + "; ".join(f"{r['witness_id']}: {r['reason']}"
                            for r in refusals))
        return sigs, refusals
