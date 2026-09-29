"""A recipient node.

What this class deliberately does *not* have is as important as what it has. It
holds no content key, no key share, and no cached plaintext. Between sessions it
holds only:

* its ML-DSA signing key (its identity -- it must have this to sign requests),
* its ML-KEM private key (used for nothing in this design's open path; it exists
  so a future "seal to recipient" mode has somewhere to go),
* the ciphertext of documents distributed to it, which is useless alone.

Every open is a network round trip. There is no offline path, no "already
opened" shortcut, and no local cache of K -- because a cached K is precisely the
thing that lets someone read a document without leaving a ledger entry, which
would make the entire system theatre.

The session's ephemeral keypair is generated inside :meth:`open` and both halves
go out of scope when it returns. That is what makes a recorded response useless:
the private half that could decapsulate it no longer exists anywhere.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

import httpx

from ..crypto import onetime, pqc
from ..crypto.ca import open_payload
from ..models import Certificate, DecryptionRequest


class OpenRefused(Exception):
    """The authority declined, or failed closed. No key material was produced."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"authority returned {status}: {detail}")


class ClientNode:
    def __init__(self, recipient_id: str, cert: Certificate,
                 sig_sec: bytes, authority_url: str = "https://127.0.0.1:8443",
                 device_fp: str = "unbound-device",
                 cert_path: str | None = None, key_path: str | None = None,
                 ca_path: str | None = None, verify: bool = True,
                 tardos_code=None, user_index: int = -1, n_users: int = 0,
                 max_colluders: int = 2, eps: float = 1e-3):
        self.recipient_id = recipient_id
        self.cert = cert
        self.sig_sec = sig_sec
        self.authority_url = authority_url.rstrip("/")
        self.device_fp = device_fp
        # The fingerprinting code this recipient's copies carry, and its index
        # within it. In a real deployment the distributor hands these out; a
        # recipient knowing their own codeword is not a weakness, since framing
        # another user would require *their* codeword.
        self.tardos_code = tardos_code
        self.user_index = user_index
        self.n_users = n_users
        self.max_colluders = max_colluders
        self.eps = eps
        self._tls = None
        if cert_path and key_path and ca_path:
            self._tls = (cert_path, key_path, ca_path)
        elif not verify:
            self._tls = None

    # -- transport ---------------------------------------------------------

    def _client(self) -> httpx.Client:
        if self._tls:
            cert_path, key_path, ca_path = self._tls
            return httpx.Client(cert=(cert_path, key_path), verify=ca_path,
                                timeout=15.0)
        # No TLS material supplied: plain HTTP. Only reachable when the caller
        # explicitly constructed the node without certs, and the authority will
        # still demand a valid ML-DSA signature over the body.
        return httpx.Client(verify=False, timeout=15.0)

    # -- the open ----------------------------------------------------------

    def build_request(self, doc_id: str, ephemeral_kem_pub: bytes,
                      nonce: str | None = None) -> DecryptionRequest:
        """Assemble and sign the request. Exposed for tests and for the demo UI
        to show the exact bytes that will become the ledger entry."""
        dr = DecryptionRequest(
            doc_id=doc_id,
            recipient_id=self.recipient_id,
            nonce=nonce or secrets.token_hex(16),
            timestamp=datetime.now(timezone.utc).isoformat(),
            device_fp=self.device_fp,
            ephemeral_kem_pub=ephemeral_kem_pub.hex(),
        )
        dr.sig = pqc.sign(self.sig_sec, dr.tbs(), pqc.SIG).hex()
        return dr

    def mark_copy(self, plaintext: str, ledger_index: int,
                  watermark_seed_hex: str) -> tuple[str, dict]:
        """Embed this session's watermark into a freshly decrypted copy.

        This runs on the *client*, immediately after decryption, and it is why
        the seed is bound to the ledger entry rather than to the document: the
        same recipient opening the same document twice produces two differently
        marked copies, each traceable to one specific session.

        The layout is derived here rather than taken from the server's response.
        The authority could send a layout that does not match what the
        investigator will compute, and the result would be a copy whose mark
        silently fails to decode -- a denial of the very evidence trail the
        system exists to produce. Deriving it locally removes that dependency.
        """
        from ..watermark import linguistic, payload

        slots = linguistic.slot_count(plaintext)
        plan = payload.plan_for_document(slots, self.n_users,
                                         self.max_colluders, self.eps)
        if not plan["ok"]:
            return plaintext, plan

        tardos_bits = None
        if plan["tardos_bits"] and self.tardos_code is not None \
                and self.user_index >= 0:
            tardos_bits = self.tardos_code.codeword(self.user_index,
                                                    plan["tardos_bits"])

        bits = payload.build_payload(ledger_index, tardos_bits)
        marked, _ = linguistic.embed(plaintext, bits,
                                     bytes.fromhex(watermark_seed_hex),
                                     masked_bits=plan["pointer_bits"])
        return marked, plan

    def open(self, doc_id: str, mark: bool = False) -> dict:
        """The full one-time open. Returns ``{plaintext, watermark_seed, ...}``.

        With ``mark=True`` the returned dict also carries ``marked_text``: the
        decrypted document with this session's watermark embedded, which is the
        artefact the recipient actually keeps. ``plaintext`` is still returned so
        a caller can diff the two and see exactly which words the mark changed.

        ``distribution_pdf`` is the PDF that was sealed at distribution, and it
        is returned as bytes rather than written anywhere: this class holds no
        key material between sessions and it does not write files either. The
        marked copy is a *different* PDF, rendered from ``marked_text`` by
        :func:`logfirst.pdfdoc.render` -- see that module for why the mark
        cannot be baked in at distribution.

        Raises :class:`OpenRefused` on any refusal, including the authority
        failing closed because the ledger could not be extended. In that case
        no key was released and nothing was written.
        """
        # Fresh keypair for this single open, destroyed on return.
        eph_pub, eph_sec = pqc.kem_keypair(pqc.KEM)
        dr = self.build_request(doc_id, eph_pub)

        with self._client() as c:
            try:
                r = c.post(f"{self.authority_url}/open", json=dr.__dict__)
            except Exception as e:
                raise OpenRefused(0, f"authority unreachable: {e}") from e
            if r.status_code != 200:
                raise OpenRefused(r.status_code, r.text)
            receipt = r.json()["receipt"]

        # Recover K from the one-time blob. This is the only moment K exists on
        # this machine, and it is a local variable.
        content_key = onetime.unwrap_session(eph_sec, receipt["one_time_key"])
        package = {"doc_id": receipt["doc_id"], "nonce": receipt["nonce"],
                   "ciphertext": receipt["ciphertext"]}
        payload = open_payload(package, content_key)
        plaintext = payload["text"]

        # Drop the key material. `del` is not a security boundary in CPython --
        # the bytes may survive in freed memory -- but it is the honest
        # expression of intent, and the real guarantee is that K was never
        # written to disk in the first place. README states this limit.
        del content_key
        del eph_sec

        out = {
            "plaintext": plaintext,
            "watermark_seed": receipt["watermark_seed"],
            "ledger_index": receipt["index"],
            "leaf_hash": receipt["leaf_hash"],
            "inclusion_proof": receipt["inclusion_proof"],
            "tree_size": receipt["tree_size"],
            "sth": receipt["sth"],
            "classification": receipt.get("classification"),
            "caveat": receipt.get("attribution_caveat"),
            # The PDF that was sealed at distribution, returned as bytes and not
            # written anywhere. This is the document as distributed; the marked
            # copy is a *second* rendering, made from marked_text below, and the
            # two are deliberately different files.
            "distribution_pdf": payload["pdf"],
            "payload_manifest": payload["manifest"],
        }
        if mark:
            marked, plan = self.mark_copy(plaintext, receipt["index"],
                                          receipt["watermark_seed"])
            out["marked_text"] = marked
            out["marking_plan"] = plan
        return out

    def seal_for_distribution(self, doc_id: str, classification: str,
                              text: str, recipients: list[str]) -> dict:
        """Ask the authority to distribute a document. Sender-side helper."""
        with self._client() as c:
            r = c.post(f"{self.authority_url}/documents",
                       json={"doc_id": doc_id, "classification": classification,
                             "text": text, "recipients": recipients})
            if r.status_code != 200:
                raise OpenRefused(r.status_code, r.text)
            return r.json()
