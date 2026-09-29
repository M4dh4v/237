"""The key authority: the network-facing service that holds the only copy of K.

The ordering in :meth:`Authority.open_document` is the entire security claim of
this project, so it is worth reading the sequence rather than skimming it:

1. Is the caller a recipient we know, and not revoked?
2. Is this document granted to them?
3. Does the request carry a valid ML-DSA signature from *their* key, over a
   body that includes the ephemeral key the response will be wrapped to?
4. **Commit the signed request to the ledger and obtain a witness quorum.**
5. Only then: unwrap K and re-wrap it to the caller's ephemeral key.

Steps 1-3 are ordinary authorisation and could be done by any server. Step 4
before step 5 is what makes the ledger a precondition for decryption rather
than an audit trail written afterwards. If step 4 raises -- a witness is down, a
witness refuses, the database is locked, the disk is full -- the exception
propagates and no key material is ever produced. There is no branch that
degrades to releasing the key anyway, and tests/test_authority.py asserts that
by killing witnesses mid-flight and checking that the response is a refusal.

A second consequence of the ordering: the watermark seed returned in step 5 is
derived from the ledger entry committed in step 4. The mark on the copy and the
record in the log are therefore the same event, not two records that happen to
agree.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .. import pdfdoc
from ..crypto import ca as ca_mod
from ..crypto import onetime, pqc
from ..ledger import merkle
from ..ledger.anchor import Anchorer
from ..ledger.log import LedgerLog, STHNotWitnessed
from ..models import DecryptionRequest, canon
from .store import Store

# Every attribution result carries this. It is not boilerplate: the system
# proves which key signed, and a key is not a person. See README "Honesty".
ATTRIBUTION_CAVEAT = (
    "Cryptographic attribution identifies the key, device and session that "
    "decrypted this document, and the signature that authorised it. It does "
    "not establish that a particular human being leaked it. If a key was "
    "shared, copied or stolen, this evidence points at the holder of that key."
)


class DecryptionDenied(Exception):
    """Any refusal to release. Carries a machine-readable reason code."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class Authority:
    def __init__(self, log: LedgerLog, store: Store, ca_pub: bytes,
                 server_kem_pub: bytes, server_kem_sec: bytes,
                 anchorer: Anchorer | None = None):
        self.log = log
        self.store = store
        self.ca_pub = ca_pub
        self.server_kem_pub = server_kem_pub
        self.anchorer = anchorer
        # The authority's KEM private key. In a real deployment this is in an
        # HSM and is the single most sensitive secret in the system: it opens
        # every document ever distributed. Here it is a constructor argument,
        # and README says so.
        self.server_kem_sec = server_kem_sec

    # -- distribution ------------------------------------------------------

    def seal(self, plaintext: bytes, doc_id: str, classification: str,
             recipients: list[str]) -> dict:
        """Encrypt a document to the authority and grant it to recipients.

        Note that no recipient key is used here at all. Granting is a database
        row, not a cryptographic act, because the cryptography that matters
        happens per-open and per-recipient later. This is the structural
        difference from the split-key design, where granting *was* the
        cryptographic act and a granted recipient could thereafter open the
        document offline.

        The document is rendered to PDF here, and the PDF is sealed *with* the
        text rather than being re-rendered by whoever opens it later. That makes
        the artefact inside the envelope the artefact that was distributed: two
        renderings of the same prose are two files, and only one of them was
        sealed.

        The rendering happens before any of this reaches the ledger, and
        ``open_document`` is untouched by it -- nothing in this method appends,
        witnesses or releases anything.
        """
        unknown = [r for r in recipients if self.store.get_cert(r) is None]
        if unknown:
            raise DecryptionDenied("unknown-recipient", ", ".join(unknown))

        text = (plaintext.decode("utf-8") if isinstance(plaintext, (bytes,
                                                                   bytearray))
                else plaintext)
        created = datetime.now(timezone.utc)
        rendered = pdfdoc.render(text, doc_id=doc_id,
                                 classification=classification, created=created)
        if rendered.replaced:
            # The PDF is not a faithful rendering, which for a document that is
            # about to be watermarked and traced is not a detail. Refusing here
            # is the whole reason the renderer counts substitutions.
            raise DecryptionDenied(
                "document-cannot-be-rendered-faithfully",
                f"{rendered.replaced} character(s) the font "
                f"{rendered.font} cannot draw")

        package = ca_mod.encrypt_framed_payload(
            text, rendered.data, doc_id, classification, self.server_kem_pub,
            extra_manifest={"created": created.isoformat(),
                            "font": rendered.font,
                            "pages": rendered.pages})
        self.store.add_document(package, recipients)
        return package

    # -- the gate ----------------------------------------------------------

    def open_document(self, dr: DecryptionRequest,
                      source_ip: str | None = None) -> dict:
        """Verify, then commit, then -- only then -- release.

        Raises :class:`DecryptionDenied` for authorisation failures and
        :class:`STHNotWitnessed` when the ledger cannot be extended. Both mean
        the caller receives no key material.
        """
        # 1. known recipient
        cert = self.store.get_cert(dr.recipient_id)
        if cert is None:
            raise DecryptionDenied("unknown-recipient", dr.recipient_id)
        if self.store.is_revoked(dr.recipient_id):
            raise DecryptionDenied("recipient-revoked", dr.recipient_id)

        # 2. the certificate really was issued by the offline CA
        if not ca_mod.CA(self.ca_pub, b"").verify(cert):
            raise DecryptionDenied("bad-certificate-signature",
                                   dr.recipient_id)

        # 3. authorized for this document, default-deny
        if not self.store.is_authorized(dr.doc_id, dr.recipient_id):
            raise DecryptionDenied("not-authorized-for-document",
                                   f"{dr.recipient_id} / {dr.doc_id}")

        # 4. the request is signed by the key the CA bound to this identity.
        #    This is the non-repudiation check, and it covers the ephemeral
        #    key, so the response cannot be redirected in transit.
        if not dr.sig:
            raise DecryptionDenied("unsigned-request")
        if not pqc.verify(bytes.fromhex(cert.sig_pub), dr.tbs(),
                          bytes.fromhex(dr.sig)):
            raise DecryptionDenied("bad-request-signature", dr.recipient_id)

        package = self.store.get_document(dr.doc_id)
        if package is None:
            raise DecryptionDenied("unknown-document", dr.doc_id)

        # 5. COMMIT FIRST. Anything below this line is unreachable if the
        #    ledger cannot be extended with a witness quorum.
        receipt = self.log.gated_append_for_decryption(dr.leaf_bytes(),
                                                       source_ip=source_ip)

        # 6. Now, and only now, derive key material.
        content_key = onetime.unseal_content_key(
            self.server_kem_sec, package["key_envelope"])
        one_time = onetime.wrap_for_session(
            bytes.fromhex(dr.ephemeral_kem_pub), content_key)

        self.store.record_session(dr.doc_id, dr.recipient_id, receipt["index"],
                                  receipt["leaf_hash"], receipt["watermark_seed"],
                                  released=True, source_ip=source_ip,
                                  device_fp=dr.device_fp)

        return {
            "one_time_key": one_time,
            "watermark_seed": receipt["watermark_seed"],
            "inclusion_proof": receipt["inclusion_proof"],
            "leaf_hash": receipt["leaf_hash"],
            "index": receipt["index"],
            "tree_size": receipt["sth"].tree_size,
            "sth": receipt["sth"].to_dict(),
            "witness_refusals": receipt["witness_refusals"],
            "doc_id": dr.doc_id,
            "classification": package["classification"],
            "cipher": package["cipher"],
            "nonce": package["nonce"],
            "ciphertext": package["ciphertext"],
            "attribution_caveat": ATTRIBUTION_CAVEAT,
        }

    # -- anchoring ---------------------------------------------------------

    def anchor_now(self) -> dict | None:
        if self.anchorer is None:
            return None
        return self.anchorer.anchor(self.log.tree_size(),
                                    self.log.current_root().hex())


def make_authority(log: LedgerLog, store: Store, ca_pub: bytes,
                   server_kem_pub: bytes, server_kem_sec: bytes,
                   anchorer: Anchorer | None = None) -> Authority:
    """Build an Authority with its KEM keypair wired in."""
    return Authority(log, store, ca_pub, server_kem_pub, server_kem_sec,
                     anchorer=anchorer)


# --------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------

class OpenBody(BaseModel):
    doc_id: str
    recipient_id: str
    nonce: str
    timestamp: str
    device_fp: str
    ephemeral_kem_pub: str
    sig: str


class SealBody(BaseModel):
    doc_id: str
    classification: str
    text: str
    recipients: list[str]


def build_app(auth: Authority, scenario=None) -> FastAPI:
    """The authority's HTTP surface.

    ``scenario`` is optional and only adds the demo and leak-check routes
    (:mod:`logfirst.authority.demo_api`). It is optional so that
    ``tests/test_authority_http.py`` can exercise the real gate without a demo
    deployment attached, and so that a production-shaped run has no demo routes
    on it at all.
    """
    app = FastAPI(title="logfirst key authority", version="1.0")

    if scenario is not None:
        from .demo_api import register_demo_routes
        register_demo_routes(app, scenario)

    def _sth_dict(sth):
        return sth.to_dict() if sth else None

    @app.get("/health")
    def health():
        return {"ok": True, "auth": "mTLS + ML-DSA request signature",
                "tree_size": auth.log.tree_size(),
                "root": auth.log.current_root().hex(),
                "documents": len(auth.store.documents()),
                "recipients": len(auth.store.recipients()),
                "witnesses": auth.log.quorum.witness_ids(),
                "min_witnesses": auth.log.quorum.min_witnesses}

    @app.get("/ledger/head")
    def ledger_head():
        sth = auth.log.latest_sth()
        return {"tree_size": auth.log.tree_size(),
                "root": auth.log.current_root().hex(),
                "log_pub": auth.log.log_pub.hex(),
                "witnesses": auth.log.quorum.witness_ids(),
                "min_witnesses": auth.log.quorum.min_witnesses,
                "sth": _sth_dict(sth)}

    @app.get("/ledger/entry/{index}")
    def ledger_entry(index: int):
        try:
            leaf = auth.log.get_leaf(index)
            proof = [p.hex() for p in auth.log.inclusion_proof(index)]
        except IndexError:
            raise HTTPException(404, f"no entry at index {index}")
        sth = auth.log.latest_sth()
        return {"index": index, "leaf": leaf.decode("utf-8"),
                 "leaf_hash": merkle.leaf_hash(leaf).hex(),
                 "inclusion_proof": proof,
                 "tree_size": sth.tree_size if sth else 0,
                 "root": sth.root_hash if sth else None,
                 "sth": _sth_dict(sth)}

    @app.get("/ledger/entries")
    def ledger_entries(limit: int = 50, order: str = "desc"):
        n = auth.log.tree_size()
        idxs = range(n - 1, max(-1, n - 1 - limit), -1) if order == "desc" \
            else range(0, min(n, limit))
        out = []
        for i in idxs:
            leaf = auth.log.get_leaf(i)
            out.append({"index": i, "leaf_hash": merkle.leaf_hash(leaf).hex(),
                        "leaf": leaf.decode("utf-8")})
        return {"tree_size": n, "entries": out}

    @app.get("/ledger/proof/{index}")
    def ledger_proof(index: int, tree_size: int | None = None):
        n = tree_size or auth.log.tree_size()
        try:
            proof = auth.log.consistency_proof(index, n)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"from_size": index, "to_size": n,
                "proof": [p.hex() for p in proof],
                "from_root": merkle.root_from_hashes(
                    auth.log.leaf_hashes()[:index]).hex(),
                "to_root": merkle.root_from_hashes(
                    auth.log.leaf_hashes()[:n]).hex()}

    @app.get("/witnesses")
    def witnesses():
        out = []
        for c in auth.log.quorum.clients:
            try:
                info = c.info()
                out.append({"witness_id": c.witness_id, "url": c.base_url,
                            "pub": info["pub"], "max_size": c.max_size(),
                            "reachable": True})
            except Exception as e:
                out.append({"witness_id": c.witness_id, "url": c.base_url,
                            "reachable": False, "error": str(e)})
        return {"min_witnesses": auth.log.quorum.min_witnesses,
                "witnesses": out}

    @app.post("/documents")
    def seal_document(body: SealBody):
        try:
            package = auth.seal(body.text.encode("utf-8"), body.doc_id,
                                body.classification, body.recipients)
        except DecryptionDenied as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "doc_id": package["doc_id"],
                "doc_hash": package["doc_hash"],
                "classification": package["classification"],
                "grants": auth.store.grants_for(package["doc_id"])}

    @app.get("/documents")
    def documents():
        return {"documents": auth.store.documents()}

    @app.post("/open")
    def open_document(body: OpenBody, request: Request):
        dr = DecryptionRequest(**body.model_dump())
        ip = request.client.host if request.client else None
        try:
            return {"ok": True,
                    "receipt": auth.open_document(dr, source_ip=ip)}
        except STHNotWitnessed as e:
            # 503, not 500: the service is intact, the ledger could not be
            # extended. The caller is entitled to retry, and gets no key.
            raise HTTPException(503, f"fail-closed: {e}")
        except DecryptionDenied as e:
            raise HTTPException(403, f"{e.reason}: {e.detail}")

    @app.post("/anchor")
    def anchor():
        rec = auth.anchor_now()
        if rec is None:
            raise HTTPException(400, "no anchorer configured")
        return {"ok": True, "anchor": rec}

    @app.get("/anchors")
    def anchors():
        if auth.anchorer is None:
            return {"anchors": []}
        return {"anchors": auth.anchorer.records()}

    return app


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run the logfirst key authority.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--data", default="demo-out")
    ap.add_argument("--witness-ports", default="9101,9102,9103")
    ap.add_argument("--min-witnesses", type=int, default=2)
    ap.add_argument("--no-tls", action="store_true",
                    help="serve plain HTTP (console/dev only; says so on stdout)")
    args = ap.parse_args(argv)

    from ..ledger.witnesses import WitnessClient, WitnessQuorum
    clients = [WitnessClient(f"w{i}", f"http://127.0.0.1:{p}")
               for i, p in enumerate(args.witness_ports.split(","), start=1)]
    quorum = WitnessQuorum(clients, min_witnesses=args.min_witnesses)
    log = LedgerLog.open(f"{args.data}/ledger.db", quorum,
                         check_same_thread=False)
    store = Store.open(f"{args.data}/store.db", check_same_thread=False)
    ca_pub, kem_pub = _load_deployment_keys(args.data)
    anchorer = Anchorer.open(f"{args.data}/anchors.jsonl")
    auth = Authority(log, store, ca_pub, kem_pub, _load_kem_sec(args.data),
                     anchorer=anchorer)

    import uvicorn
    app = build_app(auth)
    if args.no_tls:
        print("WARNING: serving plain HTTP; mTLS is disabled for this run.")
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    else:
        from ..crypto.mtls import MTLSFactory
        factory = MTLSFactory.open(f"{args.data}/mtls")
        srv = factory.issue("authority", f"{args.data}/mtls", server=True)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning",
                    ssl_certfile=srv["cert"], ssl_keyfile=srv["key"],
                    ssl_ca_certs=factory.ca_path, ssl_cert_reqs=2)


def _load_deployment_keys(data_dir: str):
    import json
    import os
    with open(os.path.join(data_dir, "deployment.json"), "r",
              encoding="utf-8") as f:
        d = json.load(f)
    return bytes.fromhex(d["ca_pub"]), bytes.fromhex(d["server_kem_pub"])


def _load_kem_sec(data_dir: str) -> bytes:
    import json
    import os
    with open(os.path.join(data_dir, "deployment.json"), "r",
              encoding="utf-8") as f:
        d = json.load(f)
    return bytes.fromhex(d["server_kem_sec"])


if __name__ == "__main__":
    main()
