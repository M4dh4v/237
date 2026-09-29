"""Deployment bootstrap: keys, recipients, witness processes.

One place that knows how to stand the system up, so the demo, the tests and the
synthetic-data generator all configure it the same way. Getting this wrong in
three places is how you end up with a test that passes against a quorum of one.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time

import httpx

from .. import proc
from ..crypto import ca as ca_mod
from ..crypto import pqc
from ..crypto.mtls import MTLSFactory
from ..ledger.anchor import Anchorer
from ..ledger.log import LedgerLog
from ..ledger.witnesses import WitnessClient, WitnessQuorum

DEFAULT_WITNESS_PORTS = [9101, 9102, 9103]


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _device_fp(recipient_id: str, salt: str) -> str:
    digest = hashlib.sha256(
        f"logfirst-device|{recipient_id}|{salt}".encode("utf-8")).hexdigest()
    return f"sha256:{digest[:32]}"


def _mint_device_fp(recipient_id: str) -> dict:
    """Mint a device identity for a recipient at enrolment.

    A fingerprint, not a device: nothing here reads real hardware. In a real
    deployment this value would come off the enrolling machine -- a TPM
    endorsement key, a device certificate -- and would be *attested* by that
    machine rather than asserted by the client. Here it is a random salt hashed
    with the recipient id, which yields the properties the rest of the system
    needs in order to carry and display it (per-recipient, stable, reproducible
    from the deployment file) and none of the ones that would make it evidence.
    The distinction is the reason :data:`SIMULATED` says so out loud.
    """
    salt = secrets.token_hex(16)
    return {"fingerprint": _device_fp(recipient_id, salt), "salt": salt}


class Deployment:
    """A configured deployment on disk. Does not start anything by itself."""

    def __init__(self, data_dir: str):
        self.data_dir = os.path.abspath(data_dir)
        d = _read_json(self.path("deployment.json"))
        self.ca_pub = bytes.fromhex(d["ca_pub"])
        self.ca_sec = bytes.fromhex(d["ca_sec"]) if d.get("ca_sec") else None
        self.server_kem_pub = bytes.fromhex(d["server_kem_pub"])
        self.server_kem_sec = bytes.fromhex(d["server_kem_sec"])
        self.witness_ports = d["witness_ports"]
        self.min_witnesses = d["min_witnesses"]
        self.ca = ca_mod.CA(self.ca_pub, self.ca_sec) if self.ca_sec else None

    def path(self, *parts: str) -> str:
        return os.path.join(self.data_dir, *parts)

    # -- construction ------------------------------------------------------

    @classmethod
    def create(cls, data_dir: str,
               witness_ports: list[int] | None = None,
               min_witnesses: int = 2) -> "Deployment":
        os.makedirs(data_dir, exist_ok=True)
        witness_ports = witness_ports or list(DEFAULT_WITNESS_PORTS)
        server_kem_pub, server_kem_sec = pqc.kem_keypair(pqc.KEM)
        ca = ca_mod.CA.create()
        _write_json(os.path.join(data_dir, "deployment.json"), {
            "ca_pub": ca.sig_pub.hex(),
            # Demo-only: this file also holds the CA private key and the
            # authority's KEM private key, which in a real deployment live in
            # an HSM and an offline machine respectively. README says so.
            "ca_sec": ca.sig_sec.hex(),
            "server_kem_pub": server_kem_pub.hex(),
            "server_kem_sec": server_kem_sec.hex(),
            "witness_ports": witness_ports,
            "min_witnesses": min_witnesses,
        })
        MTLSFactory.open(os.path.join(data_dir, "mtls"))
        return cls(data_dir)

    # -- identities --------------------------------------------------------

    def add_recipient(self, recipient_id: str, role: str = "recipient"):
        cert, secrets = ca_mod.enroll_recipient(self.ca, recipient_id, role=role)
        people_path = self.path("recipients.json")
        people = _read_json(people_path) if os.path.exists(people_path) else {}
        people[recipient_id] = {"cert": cert.__dict__, "secrets": secrets,
                                "role": role,
                                "device": _mint_device_fp(recipient_id)}
        _write_json(people_path, people)
        return cert, secrets

    def recipients(self) -> dict:
        p = self.path("recipients.json")
        return _read_json(p) if os.path.exists(p) else {}

    def device_fp_for(self, recipient_id: str) -> str:
        """The device fingerprint enrolled for this recipient.

        Backfills on read, and writes the result back. A deployment created
        before device fingerprints existed has recipients.json entries with no
        ``device`` key, and the tempting fix -- re-enrol those recipients -- would
        mint fresh keypairs and invalidate every certificate the ledger already
        references. Adding the fingerprint beside the existing keys touches no
        key material, and persisting it keeps the value stable across restarts
        so that a ledger entry from yesterday and one from today name the same
        device.
        """
        people = self.recipients()
        rec = people.get(recipient_id)
        if rec is None:
            raise KeyError(f"no such recipient: {recipient_id}")
        device = rec.get("device") or {}
        if not device.get("fingerprint"):
            device = _mint_device_fp(recipient_id)
            rec["device"] = device
            _write_json(self.path("recipients.json"), people)
        return device["fingerprint"]

    def secrets_for(self, recipient_id: str) -> dict:
        return self.recipients()[recipient_id]["secrets"]

    def cert_for(self, recipient_id: str):
        from ..models import Certificate
        return Certificate(**self.recipients()[recipient_id]["cert"])

    def recipient_pubs(self) -> dict[str, bytes]:
        """Recipient id -> ML-DSA public key, from the issued certificates."""
        return {rid: bytes.fromhex(rec["cert"]["sig_pub"])
                for rid, rec in self.recipients().items()}

    def issue_node_cert(self, name: str) -> dict:
        factory = MTLSFactory.open(self.path("mtls"))
        return factory.issue(name, self.path("mtls"))

    def sync_store(self, store) -> int:
        """Load every recipient on disk into the authority's store.

        The CA issues certificates to a file; the authority reads them from its
        database. They are separate on purpose -- the CA is offline and the
        authority must not be able to mint identities -- but that means nothing
        reaches the authority's store unless something carries it there. Making
        that step explicit (rather than having the authority re-read the CA's
        file) keeps the authority honest about what it has actually been told.
        """
        n = 0
        for rid in self.recipients():
            store.add_recipient(self.cert_for(rid))
            n += 1
        return n

    # -- ledger ------------------------------------------------------------

    def quorum(self) -> WitnessQuorum:
        clients = [WitnessClient(f"w{i}", f"http://127.0.0.1:{p}")
                   for i, p in enumerate(self.witness_ports, start=1)]
        return WitnessQuorum(clients, min_witnesses=self.min_witnesses)

    def open_log(self, **kw) -> LedgerLog:
        return LedgerLog.open(self.path("ledger.db"), self.quorum(), **kw)

    def anchorer(self) -> Anchorer:
        return Anchorer.open(self.path("anchors.jsonl"))

    def witness_pubs(self) -> dict[str, bytes]:
        """Witness id -> ML-DSA public key, read from their state files.

        The verifier and the investigator need these to check co-signatures
        themselves. Reading them from each witness's own file (rather than from
        anything the authority publishes) is deliberate: the authority must not
        be the source of the keys used to check the authority.
        """
        out: dict[str, bytes] = {}
        for i in range(1, len(self.witness_ports) + 1):
            wid = f"w{i}"
            p = self.path(f"{wid}.json")
            if os.path.exists(p):
                out[wid] = bytes.fromhex(_read_json(p)["pub"])
        return out

    # -- Tardos ------------------------------------------------------------

    def tardos_config(self) -> dict:
        """The deployment's fingerprinting parameters, created on first use.

        The user list is frozen here in a stable order, because a Tardos
        codeword is indexed by *position in the user list*: if the marker and the
        investigator disagree about that order, every score is computed against
        the wrong person and the trace names an innocent. Freezing it in a file
        both sides read is what prevents that.
        """
        p = self.path("tardos.json")
        if not os.path.exists(p):
            _write_json(p, {
                "users": sorted(self.recipients().keys()),
                "seed": int.from_bytes(os.urandom(8), "big"),
                "colluders": 2,
                "eps": 1e-3,
            })
        return _read_json(p)

    def tardos(self, m: int):
        """The Tardos code for a document carrying ``m`` fingerprint positions.

        ``m`` is per-document because a document only carries as many Tardos
        positions as its slot count allows (see
        ``watermark.payload.plan_for_document``), and codeword positions must
        line up one-to-one with the slots that actually carry them. Generation is
        deterministic given the stored seed, so the marker and the investigator
        derive the identical code without it ever being transmitted.
        """
        from ..watermark.tardos import TardosCode

        cfg = self.tardos_config()
        return TardosCode.generate(len(cfg["users"]), c=cfg["colluders"],
                                   eps=cfg["eps"], m=m, seed=cfg["seed"])


class WitnessFleet:
    """Runs the witness nodes as separate OS processes.

    Honest labelling: these are separate *processes* on one host, not separate
    machines. That is enough to stop a compromised authority from forging a
    co-signature it never asked for -- which is the property being demonstrated
    -- but the processes share a kernel, a filesystem and an administrator, so
    they are not independent in the sense a production deployment needs. The
    demo prints this rather than letting a 3-of-3 quorum imply otherwise.
    """

    def __init__(self, deployment: Deployment, python: str | None = None,
                 cwd: str | None = None):
        self.dep = deployment
        self.python = python or sys.executable
        self.cwd = cwd or os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        self.procs: dict[str, subprocess.Popen] = {}

    def start(self, only: list[str] | None = None, wait: bool = True) -> None:
        self._check_ports_free(only)
        for i, port in enumerate(self.dep.witness_ports, start=1):
            wid = f"w{i}"
            if only and wid not in only:
                continue
            if wid in self.procs and self.procs[wid].poll() is None:
                continue
            self.procs[wid] = proc.Popen(
                [self.python, "-m", "logfirst.witness.node", "--id", wid,
                 "--port", str(port), "--state", self.dep.path(f"{wid}.json")],
                cwd=self.cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wait:
            self.wait_ready(only)

    def _check_ports_free(self, only: list[str] | None = None) -> None:
        """Refuse to start if a witness port is already answering.

        Without this, a stale witness from an earlier run silently keeps the
        port, the new process dies on bind, and the symptom is a confusing
        "witness quorum not met" from the authority -- which looks like the
        fail-closed path working when in fact nothing was ever started. Worse,
        the stale process would answer ``/cosign`` from its *old* state and
        refuse a legitimate head as a rollback, so the demo would appear to
        demonstrate tamper detection while actually demonstrating a dirty port.
        """
        for i, port in enumerate(self.dep.witness_ports, start=1):
            wid = f"w{i}"
            if only and wid not in only:
                continue
            if wid in self.procs and self.procs[wid].poll() is None:
                continue
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.4)
            except Exception:
                continue
            if r.status_code == 200:
                raise RuntimeError(
                    f"witness port {port} ({wid}) is already serving "
                    f"{r.json().get('witness_id', '?')}. A witness from a "
                    "previous run is probably still alive; its state file will "
                    "disagree with this deployment's ledger and it will refuse "
                    "every head as a rollback. Kill it (pkill -f "
                    "logfirst.witness.node) or use a different --data dir.")

    def wait_ready(self, only: list[str] | None = None, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        for i, port in enumerate(self.dep.witness_ports, start=1):
            wid = f"w{i}"
            if only and wid not in only:
                continue
            while time.time() < deadline:
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health",
                                 timeout=0.5).status_code == 200:
                        break
                except Exception:
                    time.sleep(0.1)
            else:
                raise RuntimeError(f"witness {wid} on port {port} never came up")

    def kill(self, wids: list[str]) -> None:
        for wid in wids:
            p = self.procs.get(wid)
            if p and p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()

    def stop(self) -> None:
        self.kill(list(self.procs))

    def alive(self) -> list[str]:
        return [w for w, p in self.procs.items() if p.poll() is None]

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
