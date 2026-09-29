"""End-to-end scenario: a whole deployment, built and driven from one place.

The demo, the leak-check tests and the synthetic-data generator all need the
same thing -- a running system with witnesses, recipients, documents, real open
sessions and marked copies -- and they need it configured identically, or a test
passes against a quorum of one while the demo runs with three.

Everything this builds is real: the ledger entries are produced by the actual
authority calling the actual witness processes over HTTP, and the marks are
embedded by the same code path a recipient's client uses. The parts that are
simulated are named in the class docstring rather than left for the reader to
work out.

The leak scenarios are the point. :meth:`leak_screenshot`, :meth:`leak_text` and
:meth:`leak_collusion` produce the three artefacts the leak-check pipeline is
supposed to handle, each built from a real marked copy rather than from
hand-written text.
"""

from __future__ import annotations

import os
import random

from ..authority.server import Authority
from ..authority.store import Store
from ..client.node import ClientNode
from ..watermark import linguistic, payload
from . import corpus as corpus_mod
from . import harness
from .deploy import Deployment, WitnessFleet

# Named so that every docstring and every demo line can point at one list of
# what is not real. Kept as a constant so the README, the CLI and the UI agree.
SIMULATED = (
    "witness nodes run as separate processes on this machine, not on separate "
    "hosts -- they share a kernel, a filesystem and an administrator",
    "the CA private key and the authority's KEM private key are written to "
    "deployment.json in plaintext; a real deployment keeps them offline and in "
    "an HSM respectively",
    "documents are template prose from data/corpus.py, not natural language, so "
    "the measured marker densities are achievable rather than typical",
    "the 'sender' that renders the distribution PDF is this demo server, not a "
    "separate authoring client: the seal path renders and encrypts in one place "
    "so the demo can be driven from a browser, whereas a real deployment "
    "authors and renders the document before it ever reaches the authority",
    "OCR degradation is modelled by rasterise/recompress/rescale rather than "
    "photographing a screen",
    "the device fingerprint in each request is minted by the deployment file at "
    "enrolment and asserted by the client; nothing reads real hardware and the "
    "authority never checks it, so it is a recorded claim rather than evidence "
    "of which machine was used",
)


class Scenario:
    """A live deployment: witnesses running, authority constructed, corpus built.

    Use as a context manager so the witness processes are always reaped::

        with Scenario.build("/tmp/demo") as sc:
            sc.distribute(...)
            result = sc.node("alice").open("DOC-0001", mark=True)
    """

    def __init__(self, deployment: Deployment, fleet: WitnessFleet,
                 docs: list[dict], store: Store, log, authority: Authority):
        self.dep = deployment
        self.fleet = fleet
        self.docs = docs
        self.store = store
        self.log = log
        self.authority = authority
        self._nodes: dict[str, ClientNode] = {}

    # -- construction ------------------------------------------------------

    @classmethod
    def build(cls, data_dir: str, n_docs: int = 8, target_words: int = 1600,
              seed: int = 7, recipients: list[str] | None = None,
              start_witnesses: bool = True, min_witnesses: int = 2,
              fresh: bool = False,
              witness_ports: list[int] | None = None) -> "Scenario":
        """``witness_ports`` matters more than it looks: the default ports are
        fixed, so anything that builds a scenario while another scenario is
        already running -- a test suite beside a live demo, or two test runs --
        collides on 9101 and fails with a message about a stale witness rather
        than about the port. Passing ports lets a caller that cares pick free
        ones; ``None`` keeps the deployment's defaults."""
        recipients = recipients or ["alice", "bob", "carol", "dave"]
        if fresh and os.path.isdir(data_dir):
            import shutil
            shutil.rmtree(data_dir)

        if os.path.exists(os.path.join(data_dir, "deployment.json")):
            dep = Deployment(data_dir)
            for r in recipients:
                if r not in dep.recipients():
                    dep.add_recipient(r)
        else:
            dep = Deployment.create(data_dir, min_witnesses=min_witnesses,
                                    witness_ports=witness_ports)
            for r in recipients:
                dep.add_recipient(r)

        fleet = WitnessFleet(dep)
        if start_witnesses:
            fleet.start()

        docs = corpus_mod.make_document_set(n_docs, seed=seed,
                                            target_words=target_words)
        # ``check_same_thread=False`` because the demo serves this scenario from
        # a web framework that runs handlers on a worker thread. Without it every
        # request from the front end fails on SQLite's thread check -- which
        # presents as a 500 that looks like a permissions or locking problem.
        # The connection is still used by one request at a time; FastAPI's
        # threadpool and SQLite's own locking are what make that safe here.
        store = Store.open(dep.path("authority.db"), check_same_thread=False)
        dep.sync_store(store)

        log = dep.open_log(check_same_thread=False)
        authority = Authority(log=log, store=store, ca_pub=dep.ca_pub,
                              server_kem_pub=dep.server_kem_pub,
                              server_kem_sec=dep.server_kem_sec,
                              anchorer=dep.anchorer())
        return cls(dep, fleet, docs, store, log, authority)

    def close(self) -> None:
        self.fleet.stop()

    def __enter__(self) -> "Scenario":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- identities and documents -----------------------------------------

    def node(self, recipient_id: str) -> ClientNode:
        """A client node for a recipient, wired to the in-process authority.

        Talking to the :class:`Authority` object directly rather than over HTTP
        keeps the tests fast; the HTTP surface is exercised separately in
        tests/test_authority_http.py, so this shortcut does not leave the wire
        format untested.
        """
        if recipient_id in self._nodes:
            return self._nodes[recipient_id]
        cfg = self.dep.tardos_config()
        users = cfg["users"]
        # Build a node bound to the deployment's fingerprinting code.
        code = None
        index = -1
        if recipient_id in users:
            index = users.index(recipient_id)
        node = ClientNode(
            recipient_id, self.dep.cert_for(recipient_id),
            bytes.fromhex(self.dep.secrets_for(recipient_id)["sig_sec"]),
            authority_url="in-process",
            device_fp=self.dep.device_fp_for(recipient_id),
            tardos_code=_LazyTardos(self.dep, recipient_id, index),
            user_index=index, n_users=len(users),
            max_colluders=cfg["colluders"], eps=cfg["eps"])
        # Route the node's transport at the in-process authority.
        node._client = lambda: _DirectClient(self.authority)   # noqa: SLF001
        self._nodes[recipient_id] = node
        return node

    def distribute(self, doc_id: str, recipients: list[str],
                   classification: str = "SECRET") -> dict:
        doc = self.doc(doc_id)
        return self.authority.seal(doc["text"], doc_id, classification,
                                   recipients)

    def doc(self, doc_id: str) -> dict:
        for d in self.docs:
            if d["doc_id"] == doc_id:
                return d
        raise KeyError(doc_id)

    # -- forensics ---------------------------------------------------------

    def ledger_publics(self) -> dict:
        """Everything an outsider needs to check this ledger, and nothing more.

        Public keys only, and the witnesses' taken from their own state files
        rather than from anything the authority serves -- the keys used to check
        the authority must not come from the authority. This is the same bundle
        handed to ``verifier/`` and to an auditor years later.
        """
        return {
            "log_pub": self.log.log_pub.hex(),
            "witness_pubs": {k: v.hex() for k, v in self.dep.witness_pubs().items()},
            "recipient_pubs": {k: v.hex()
                               for k, v in self.dep.recipient_pubs().items()},
            "witness_quorum": self.dep.min_witnesses,
            "ca_pub": self.dep.ca_pub.hex(),
        }

    def investigator(self, **kw) -> "Investigator":
        """The leak-check pipeline, wired to this deployment's real ledger.

        The Tardos code is generated at the formal length rather than at any one
        document's length: generation is prefix-stable (see
        ``TardosCode.codeword``), so a code of the formal length contains every
        shorter document's positions as a prefix, and one code serves the whole
        corpus. Generating it from the deployment's stored seed is what keeps the
        investigator's notion of "user 2" identical to the marker's.
        """
        from ..forensics.investigate import Investigator
        from ..watermark.tardos import code_length

        cfg = self.dep.tardos_config()
        users = cfg["users"]
        code = self.dep.tardos(code_length(len(users), cfg["colluders"],
                                           cfg["eps"]))
        kw.setdefault("docs", self.docs)
        kw.setdefault("ledger", self.log)
        kw.setdefault("log_pub", self.log.log_pub)
        kw.setdefault("witness_pubs", self.dep.witness_pubs())
        kw.setdefault("recipient_pubs", self.dep.recipient_pubs())
        kw.setdefault("tardos", code)
        kw.setdefault("user_order", users)
        kw.setdefault("witness_quorum", self.dep.min_witnesses)
        kw.setdefault("max_colluders", cfg["colluders"])
        kw.setdefault("eps", cfg["eps"])
        return Investigator(**kw)

    # -- leak scenarios ----------------------------------------------------

    def leak_text(self, recipient_id: str, doc_id: str,
                  mark: bool = True) -> dict:
        """A recipient opens a document and the marked copy is the leak.

        The simplest case, and the one that should always attribute: the leaked
        text is exactly what the client produced, with no degradation.
        """
        out = self.node(recipient_id).open(doc_id, mark=mark)
        return {"recipient_id": recipient_id, "doc_id": doc_id,
                "ledger_index": out["ledger_index"],
                "leaked_text": out.get("marked_text", out["plaintext"]),
                "opened": out}

    def leak_screenshot(self, recipient_id: str, doc_id: str,
                        attack: str = "jpeg50",
                        crop: tuple[int, int] | None = None) -> dict:
        """The marked copy rendered, degraded, cropped and OCR'd back.

        This is the realistic path: nobody leaks a .txt file, they photograph a
        screen. ``crop`` selects a (start, end) character range of the rendered
        document, modelling a leak of one page rather than the whole thing.
        """
        out = self.node(recipient_id).open(doc_id, mark=True)
        marked = out.get("marked_text", out["plaintext"])
        text = marked
        if crop:
            text = marked[crop[0]:crop[1]]
        img = harness.render(text)
        img = harness.CATALOG[attack].fn(img)
        from ..watermark import ocr
        return {"recipient_id": recipient_id, "doc_id": doc_id,
                "ledger_index": out["ledger_index"], "attack": attack,
                "image": img, "leaked_text": ocr.image_to_text(img),
                "opened": out}

    def leak_collusion(self, a: str, b: str, doc_id: str,
                       choose: str = "random", seed: int = 0) -> dict:
        """Two recipients splice their copies to destroy the per-copy mark.

        The attack respects the marking assumption: at a position where the two
        copies agree, a colluder learns nothing and cannot change it, so the
        splice only differs from copy A at positions where A and B disagree.

        Returns the spliced text plus what a *correct* tracing should recover,
        so a test can assert on the outcome rather than on a logged string.
        """
        oa = self.node(a).open(doc_id, mark=True)
        ob = self.node(b).open(doc_id, mark=True)
        ta = oa.get("marked_text", oa["plaintext"])
        tb = ob.get("marked_text", ob["plaintext"])

        from ..forensics.align import tokens as _tokens

        wa = _tokens(ta)
        wb = _tokens(tb)
        if len(wa) != len(wb):
            # The two copies are the same length by construction (substitution
            # only), so a mismatch means something upstream changed the token
            # count and the splice would be meaningless. Fail loudly.
            raise ValueError(
                f"marked copies differ in token count ({len(wa)} vs {len(wb)}); "
                "they should be token-for-token identical")

        rng = random.Random(seed)
        out = list(wa)
        flipped = 0
        for i, (x, y) in enumerate(zip(wa, wb)):
            if x == y:
                continue                      # marking assumption: untouchable
            flipped += 1
            if choose == "random":
                out[i] = x if rng.random() < 0.5 else y
            elif choose == "low":
                out[i] = min(x, y)
            elif choose == "high":
                out[i] = max(x, y)
            else:
                raise ValueError(f"unknown choose strategy {choose!r}")

        return {"doc_id": doc_id, "colluders": [a, b],
                "ledger_indices": [oa["ledger_index"], ob["ledger_index"]],
                "leaked_text": " ".join(out), "positions_differing": flipped,
                "opened": [oa, ob]}


class _LazyTardos:
    """A TardosCode whose length is only known once the document is in hand.

    The codeword length depends on how many slots the specific document offers,
    which is not known until open time. Rather than freeze a length up front and
    be wrong for every document that differs, the code is generated on first use
    with the length actually needed, and cached per length.

    Exposes ``codeword(user_index, m)`` so it is interchangeable with a real
    :class:`~logfirst.watermark.tardos.TardosCode` as far as
    :meth:`ClientNode.mark_copy` is concerned.
    """

    def __init__(self, dep: Deployment, recipient_id: str, index: int):
        self.dep = dep
        self.recipient_id = recipient_id
        self.index = index
        self._cache: dict[int, object] = {}

    def codeword(self, user_index: int, m: int | None = None):
        code = self._cache.get(m)
        if code is None:
            code = self.dep.tardos(m)
            self._cache[m] = code
        return code.codeword(user_index, m)


class _DirectClient:
    """Minimal stand-in for ``httpx.Client`` that calls the authority in-process.

    Implements only ``post`` and the context-manager protocol, which is all
    :class:`ClientNode` uses. It exists so tests exercise the real client code
    against the real authority object without paying for a socket, and it is
    deliberately dumb: it does no validation of its own, so any behaviour a test
    observes came from the authority.
    """

    def __init__(self, authority: Authority):
        self.authority = authority

    def __enter__(self) -> "_DirectClient":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def post(self, url: str, json: dict | None = None, **kw) -> "_Response":
        path = url.split("in-process", 1)[-1] or "/"
        if path == "/open":
            return self._open(json or {})
        if path == "/documents":
            return self._seal(json or {})
        return _Response(404, {"detail": f"no in-process route for {path}"})

    def _open(self, body: dict) -> "_Response":
        from ..authority.server import OpenBody          # noqa: F401
        from ..ledger.log import STHNotWitnessed
        from ..models import DecryptionRequest
        try:
            dr = DecryptionRequest(**body)
            receipt = self.authority.open_document(dr)
            return _Response(200, {"receipt": receipt})
        except STHNotWitnessed as exc:
            # Mirrors the HTTP mapping in ``build_app``'s ``/open`` route: a
            # ledger that cannot be extended is a 503, not a 403 -- the service
            # is intact and the caller may retry. Collapsing this into the
            # generic 403 branch would make the in-process tests assert a status
            # the real server never sends, so a client that keys off 503 to
            # report "fail-closed" would look correct here and be wrong on the
            # wire.
            return _Response(503, {"detail": f"fail-closed: {exc}"})
        except Exception as exc:                     # mirrors the HTTP mapping
            status = getattr(exc, "status_code", None) or 403
            return _Response(status, {"detail": str(exc)})

    def _seal(self, body: dict) -> "_Response":
        try:
            out = self.authority.seal(body["text"], body["doc_id"],
                                      body["classification"],
                                      body["recipients"])
            return _Response(200, out)
        except Exception as exc:
            return _Response(getattr(exc, "status_code", None) or 400,
                             {"detail": str(exc)})


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload

    @property
    def text(self) -> str:
        import json as _json
        return _json.dumps(self._payload)
