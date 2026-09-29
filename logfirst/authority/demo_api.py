"""HTTP surface for the demo: distribute, open, and check a leak.

This is deliberately a separate module from :mod:`logfirst.authority.server`.
Everything in ``server.py`` is the system under test -- the gate, the ledger, the
one-time key release -- and it should be readable without a demo's worth of
convenience routes around it. Everything here exists so a browser can drive the
same objects the tests drive, and nothing here is load-bearing for any security
property: removing this file leaves the guarantees intact.

That distinction is worth being strict about, because a demo endpoint is the
easiest place for a system like this to quietly acquire a shortcut. So the two
rules this module follows:

**It never does cryptography of its own.** Opening a document goes through
:meth:`ClientNode.open`, which builds a real signed request and does a real
ephemeral KEM exchange; sealing goes through :meth:`Authority.seal`. There is no
demo path that skips the ledger, and ``/demo/open`` returning successfully is
the same event as ``tests/test_authority_http.py`` exercising.

**It says what is simulated.** :data:`logfirst.data.scenario.SIMULATED` is
served on ``/demo/state`` and repeated in the leak-check response, so the
front end has one source for the disclaimer rather than a paragraph somebody
transcribed into JavaScript and can drift.

The leak-check route is the one that matters most, and it is a thin wrapper by
design: it hands bytes to :class:`Investigator` and serialises
:meth:`Investigation.as_dict`, including ``status``, ``caveat`` and the two
separate confidences. It does not summarise, rank again, or decide what to
show. A route that reformatted the result for display would be a second place
where an accusation could lose its caveat.
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import datetime, timezone

from fastapi import HTTPException, Response
from pydantic import BaseModel

from .. import sealed
from ..data.scenario import SIMULATED


class DistributeBody(BaseModel):
    doc_id: str
    recipients: list[str]
    classification: str = "SECRET"


class OpenBody(BaseModel):
    doc_id: str
    recipient_id: str
    mark: bool = True

    # The PDFs are opt-in because they are the only large thing this API
    # returns. The sealed container is a per-document artefact and gets its own
    # download route; the marked PDF is per-*session* and cannot, for the reason
    # given on :func:`register_demo_routes.demo_open`.
    include_pdf: bool = False


class LeakBody(BaseModel):
    doc_id: str | None = None
    kind: str = "text"                 # "text" | "screenshot" | "collusion"
    recipient_id: str | None = None
    second_recipient_id: str | None = None
    attack: str = "jpeg50"

    # Or hand over an artefact directly, which is what the leak-check screen
    # does when someone pastes text or uploads a screenshot of their own.
    text: str | None = None
    image_b64: str | None = None


class CheckBody(BaseModel):
    text: str | None = None
    image_b64: str | None = None
    doc_id: str | None = None      # a hint only; identification is not trusted
    note: str | None = None


class RecipientBody(BaseModel):
    recipient_id: str


def _b64_image(data: str) -> bytes:
    """Decode a browser data URL or a bare base64 payload."""
    if "," in data[:64] and data.lstrip().startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        return base64.b64decode(data, validate=True)
    except Exception as e:
        raise HTTPException(400, f"image_b64 is not valid base64: {e}") from e


def register_demo_routes(app, scenario) -> None:
    """Attach the demo and leak-check routes to ``app``.

    ``scenario`` is a :class:`logfirst.data.scenario.Scenario`: a live
    deployment with witnesses running, an authority, and the corpus it was built
    from. Passing ``None`` registers a state route that reports why the demo is
    unavailable rather than leaving a 404 that looks like a bug.
    """
    if scenario is None:
        @app.get("/demo/state")
        def demo_unavailable():
            return {"available": False,
                    "reason": "no scenario attached; start the demo with "
                              "scripts/demo.py, which builds one"}
        return

    dep = scenario.dep

    # -- what the demo is, and what it is not ------------------------------

    @app.get("/demo/state")
    def demo_state():
        sth = scenario.log.latest_sth()
        return {
            "available": True,
            "simulated": list(SIMULATED),
            "tree_size": scenario.log.tree_size(),
            "root": scenario.log.current_root().hex(),
            "sth": sth.to_dict() if sth else None,
            "min_witnesses": dep.min_witnesses,
            "witnesses": sorted(dep.witness_pubs()),
            "witness_ports": dep.witness_ports,
            "recipients": sorted(dep.recipients()),
            "tardos": {k: v for k, v in dep.tardos_config().items()
                       if k != "seed"},
            "anchors": (dep.anchorer().records()
                        if dep.anchorer() is not None else []),
            "ledger_publics": scenario.ledger_publics(),
        }

    @app.get("/demo/documents")
    def demo_documents():
        from ..watermark import linguistic, payload

        cfg = dep.tardos_config()
        out = []
        for d in scenario.docs:
            plan = payload.plan_for_document(
                linguistic.slot_count(d["text"]), len(cfg["users"]),
                cfg["colluders"], cfg["eps"])
            sealed = scenario.store.get_document(d["doc_id"]) is not None
            out.append({
                "doc_id": d["doc_id"],
                "words": len(d["text"].split()),
                "slots": linguistic.slot_count(d["text"]),
                "tardos_positions": plan["tardos_bits"],
                "tardos_required": plan["tardos_required"],
                "guarantee": plan["guarantee"],
                "sealed": sealed,
                "recipients": sorted(scenario.store.grants_for(d["doc_id"]))
                if sealed else [],
                # A preview only. The canonical text is what the investigator
                # aligns against; serving it here is fine (the defender has the
                # originals) but the leak-check screen must not use it as an
                # answer key.
                "preview": d["text"][:280],
            })
        return {"documents": out}

    # -- the files that get downloaded -------------------------------------

    @app.get("/demo/documents/{doc_id}.lfdoc")
    def demo_sealed_container(doc_id: str):
        """The distribution artefact: the document, sealed, as a file.

        Downloads the package straight from the store rather than from anything
        the browser sent, so a re-distribution cannot leave a stale envelope
        downloadable under a name that suggests it is current.

        This route **creates no session and appends no leaf**. It is the
        distribution side of the system, it releases nothing, and the file it
        hands over is useless without the authority -- which is the point of
        putting it on the wire at all. The ``key_envelope`` inside it is the
        content key wrapped to the authority's KEM *public* key: publishing it
        costs nothing, because unwrapping it needs the private half that never
        leaves the authority.

        The extension is in the path so that ``curl -O`` names the file
        correctly with no extra arguments, which is how the demo's README tells
        people to fetch it.
        """
        package = scenario.store.get_document(doc_id)
        if package is None:
            raise HTTPException(404, f"{doc_id} is not sealed yet; "
                                     "distribute it first")
        body = sealed.pack(package)

        # The doc id comes from the store, but it is about to be interpolated
        # into a response header, and a header is not a place to trust a string
        # that could contain a newline.
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", package["doc_id"])[:64] or "document"
        return Response(
            content=body,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{safe}.lfdoc"',
                "Content-Length": str(len(body)),
                # Stated in the response so a reader does not have to know the
                # format to know what they are holding.
                "X-LogFirst-Container": "lfdoc/1",
            })

    # -- distribute and open -----------------------------------------------

    @app.post("/demo/distribute")
    def demo_distribute(body: DistributeBody):
        try:
            doc = scenario.doc(body.doc_id)
        except KeyError:
            raise HTTPException(404, f"no such document {body.doc_id}")
        unknown = [r for r in body.recipients
                   if scenario.store.get_cert(r) is None]
        if unknown:
            raise HTTPException(400, f"unknown recipients: {', '.join(unknown)}")
        from ..authority.server import DecryptionDenied

        try:
            package = scenario.authority.seal(
                doc["text"], body.doc_id, body.classification,
                body.recipients)
        except DecryptionDenied as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "doc_id": package["doc_id"],
                "doc_hash": package["doc_hash"],
                "pdf_hash": package.get("pdf_hash"),
                "pages": package.get("pages"),
                "container_bytes": len(sealed.pack(package)),
                "grants": scenario.store.grants_for(package["doc_id"]),
                "note": "the document is sealed to the authority's KEM key; no "
                        "recipient key was involved and no recipient holds a "
                        "key share"}

    @app.post("/demo/open")
    def demo_open(body: OpenBody):
        """A recipient opens a document, and the ledger entry materialises.

        Returns the receipt the client got *and* the ledger entry that now
        exists for it, so the front end can show the two together -- the point
        being that they are the same event. ``diff`` lists the words the mark
        changed, so the substitution is visible rather than asserted.

        With ``include_pdf`` the response also carries two PDFs: the one that
        was sealed at distribution, and the marked copy rendered from this
        session's marked text. They ride *here* rather than on a download route
        of their own because every open appends a new ledger entry and mints a
        fresh ephemeral key -- so a cached or separately-fetched PDF would be a
        different session's artefact wearing this one's receipt. Caching the
        marked copy server-side is worse still: it would mean persisting a
        session-bound forensic artefact on the authority, which is exactly what
        putting the marking on the client avoids.

        Rendering happens strictly after :meth:`ClientNode.open` has returned,
        so a rendering failure cannot sit between the ledger append and the key
        release. If it does fail, the open has already happened and the entry
        stays; the error is reported and the caller gets no PDF, rather than
        getting an unmarked one.
        """
        if scenario.store.get_document(body.doc_id) is None:
            raise HTTPException(400, f"{body.doc_id} is not sealed yet; "
                                     "distribute it first")
        from ..client.node import OpenRefused

        try:
            out = scenario.node(body.recipient_id).open(body.doc_id,
                                                        mark=body.mark)
        except OpenRefused as e:
            # 503 when the ledger could not be extended (fail-closed, retry is
            # meaningful), 403 when the open was refused. The distinction is the
            # same one server.py makes, kept here so the UI can say which.
            code = 503 if e.status in (0, 503) else 403
            raise HTTPException(code, str(e)) from e

        idx = out["ledger_index"]
        from ..ledger import merkle

        leaf = scenario.log.get_leaf(idx)
        diff = _word_diff(out["plaintext"], out.get("marked_text", ""))
        marked_text = out.get("marked_text")
        plan = out.get("marking_plan") or {}
        pdf_marked = bool(marked_text) and plan.get("ok", True)

        response = {
            "ok": True,
            "receipt": {k: v for k, v in out.items()
                        if k not in ("plaintext", "marked_text", "caveat",
                                     "distribution_pdf", "payload_manifest")},
            "plaintext": out["plaintext"],
            "marked_text": marked_text,
            "mark_diff": diff,
            "ledger_entry": {
                "index": idx,
                "leaf": leaf.decode("utf-8"),
                "leaf_hash": merkle.leaf_hash(leaf).hex(),
            },
            "caveat": out.get("caveat"),
            # The manifest that travelled *inside* the encryption, returned so a
            # reader can finally check the container's header against something
            # authenticated. Before an open the header is a label anyone holding
            # the file could have written; this is the value it has to agree
            # with, and `sealed.compare` is the comparison. It is returned
            # whether or not PDFs were asked for, because the check has nothing
            # to do with the PDFs.
            "payload_manifest": out.get("payload_manifest"),
        }

        if body.include_pdf:
            from .. import pdfdoc

            canonical = out.get("distribution_pdf") or b""
            response["distribution_pdf_b64"] = base64.b64encode(canonical).decode()
            response["distribution_pdf_sha256"] = hashlib.sha256(canonical).hexdigest()

            # A document too short to carry a mark decodes to the plaintext, and
            # a PDF of it would look exactly like a marked one. Saying so is the
            # difference between evidence and a file with a confident label.
            response["pdf_marked"] = pdf_marked
            if marked_text:
                marked = pdfdoc.render(
                    marked_text, doc_id=body.doc_id,
                    classification=out.get("classification") or "UNCLASSIFIED",
                    created=datetime.now(timezone.utc),
                    recipient_id=body.recipient_id,
                    ledger_index=idx, leaf_hash=out["leaf_hash"])
                response["marked_pdf_b64"] = base64.b64encode(marked.data).decode()
                response["marked_pdf_sha256"] = hashlib.sha256(marked.data).hexdigest()
                response["marked_pdf_pages"] = marked.pages

        return response

    # -- making a leak to check --------------------------------------------

    @app.post("/demo/leak")
    def demo_leak(body: LeakBody):
        """Produce a leak artefact from a real open, for the leak-check screen.

        This exists so the demo can be driven without a second terminal. It is
        *not* how the leak-check pipeline gets its input in the interesting
        case: the screen also accepts a pasted text or an uploaded image, and
        that path never touches this route.
        """
        if body.kind == "text":
            doc_id = body.doc_id or scenario.docs[0]["doc_id"]
            out = scenario.leak_text(body.recipient_id or "alice", doc_id)
            return {"kind": "text", "leaked_text": out["leaked_text"],
                    "truth": _truth("text", out)}
        if body.kind == "screenshot":
            doc_id = body.doc_id or scenario.docs[0]["doc_id"]
            out = scenario.leak_screenshot(body.recipient_id or "alice", doc_id,
                                           attack=body.attack)
            import io

            buf = io.BytesIO()
            out["image"].save(buf, format="PNG")
            return {"kind": "screenshot",
                    "image_b64": base64.b64encode(buf.getvalue()).decode(),
                    "leaked_text": out["leaked_text"],
                    "attack": out["attack"],
                    "truth": _truth("screenshot", out)}
        if body.kind == "collusion":
            doc_id = body.doc_id or scenario.docs[0]["doc_id"]
            out = scenario.leak_collusion(body.recipient_id or "alice",
                                          body.second_recipient_id or "bob",
                                          doc_id)
            return {"kind": "collusion", "leaked_text": out["leaked_text"],
                    "positions_differing": out["positions_differing"],
                    "truth": _truth("collusion", out)}
        raise HTTPException(400, f"unknown leak kind {body.kind!r}")

    # -- the leak check itself ---------------------------------------------

    @app.post("/leakcheck")
    def leakcheck(body: CheckBody):
        """Run the leak-check pipeline and return the result unsummarised."""
        text = body.text or ""
        image = _b64_image(body.image_b64) if body.image_b64 else None
        if not text.strip() and image is None:
            raise HTTPException(400, "nothing to check: pass text or image_b64")
        inv = scenario.investigator().investigate(leaked_text=text,
                                                  image_bytes=image)
        result = inv.as_dict()
        result["simulated"] = list(SIMULATED)
        if body.note:
            # Recorded, never acted on. An analyst's hunch is not evidence, and
            # letting it steer the pipeline would make the output an opinion.
            result["note"] = body.note
        return result

    @app.get("/leakcheck/example/{kind}")
    def leakcheck_example(kind: str, recipient_id: str = "alice"):
        """A ready-made artefact for the leak-check screen's 'try one' buttons."""
        if kind not in ("text", "screenshot", "collusion"):
            raise HTTPException(404, f"unknown example {kind!r}")
        if kind == "collusion":
            out = scenario.leak_collusion(recipient_id, "bob",
                                          scenario.docs[0]["doc_id"])
        elif kind == "screenshot":
            out = scenario.leak_screenshot(recipient_id,
                                           scenario.docs[0]["doc_id"])
        else:
            out = scenario.leak_text(recipient_id, scenario.docs[0]["doc_id"])
        payload = {"kind": kind, "leaked_text": out["leaked_text"],
                   "truth": _truth(kind, out)}
        if kind == "screenshot":
            import io

            buf = io.BytesIO()
            out["image"].save(buf, format="PNG")
            payload["image_b64"] = base64.b64encode(buf.getvalue()).decode()
        return payload

    # -- administration ----------------------------------------------------
    #
    # Three routes, and they are the only ones here that change what the
    # authority will and will not do for a recipient -- everything else in this
    # module reads. They are registered with the rest of the demo surface for a
    # reason worth stating: they have no authentication, and `build_app`'s
    # gating means a production-shaped run has none of them on it. Admin-as-
    # trusted is the demo's assumption, so the demo is where this lives.

    @app.get("/demo/admin/recipients")
    def admin_recipients():
        """Every recipient the authority knows, and what it knows about them.

        Read out of the authority's own store rather than the CA's file, because
        the store is what decides whether an open succeeds. Where the two could
        disagree, that is the interesting part -- so the enrolled device
        fingerprint and the one that came in on the last open are both shown,
        side by side, with the note saying the authority does not compare them.
        """
        from ..crypto import ca as ca_mod

        ca = ca_mod.CA(scenario.authority.ca_pub, b"")
        out = []
        for row in scenario.store.recipients():
            rid = row["recipient_id"]
            cert = scenario.store.get_cert(rid)
            sessions = scenario.store.sessions_for(rid)
            out.append({
                "recipient_id": rid,
                "role": row["role"],
                "revoked": row["revoked"],
                "serial": cert.serial if cert else None,
                "issued_at": cert.issued_at if cert else None,
                "kem_alg": cert.kem_alg if cert else None,
                "sig_alg": cert.sig_alg if cert else None,
                # A certificate the CA did not sign is worth seeing here rather
                # than first at open time, where it presents as a refusal with
                # no clue that the stored certificate is the problem.
                "ca_signature_ok": bool(cert) and ca.verify(cert),
                "device_fp": _enrolled_device_fp(scenario.dep, rid),
                "last_seen_device_fp": (sessions[0]["device_fp"]
                                        if sessions else None),
                "granted": scenario.store.grants_count(rid),
                "opened": len(sessions),
            })
        return {
            "recipients": out,
            "note": "Device fingerprints are recorded, not enforced: the "
                    "authority never compares the enrolled value with the one on "
                    "a request, and neither is evidence of which machine was "
                    "used.",
        }

    def _set_revoked(recipient_id: str, revoked: bool) -> dict:
        if scenario.store.get_cert(recipient_id) is None:
            raise HTTPException(404, f"no such recipient: {recipient_id}")
        if revoked:
            scenario.store.revoke(recipient_id)
        else:
            scenario.store.reinstate(recipient_id)
        # Worded per direction. The caveat is the same either way, but a note
        # that says "a copy already opened cannot be recalled" under a
        # *reinstate* reads as though the button did the opposite thing.
        return {
            "ok": True, "recipient_id": recipient_id, "revoked": revoked,
            "note": (
                "Takes effect at the next open, before any signature is "
                "verified and before anything is committed to the ledger. A copy "
                "already opened cannot be recalled, and no key material is "
                "destroyed -- the recipient still holds the private key their "
                "certificate was issued for, which is why reinstating is one "
                "flag write."
            ) if revoked else (
                "Takes effect at the next open. The certificate was never "
                "withdrawn and no key was destroyed, so this restores exactly "
                "the identity that was there before -- it does not re-enrol "
                "anyone, and the entries already in the ledger still name the "
                "opens that happened while they were revoked."
            ),
        }

    @app.post("/demo/admin/revoke")
    def admin_revoke(body: RecipientBody):
        return _set_revoked(body.recipient_id, True)

    @app.post("/demo/admin/reinstate")
    def admin_reinstate(body: RecipientBody):
        return _set_revoked(body.recipient_id, False)


def _enrolled_device_fp(dep, recipient_id: str) -> str | None:
    """The device fingerprint the CA enrolled for this recipient, if any.

    ``None`` rather than a raise when the recipient is in the authority's store
    but not in the CA's file. That is a real state -- the authority can be told
    about a recipient by something other than this deployment's own bootstrap --
    and an admin screen that 500s because one row is unusual is worse than one
    that shows a blank where the value is missing.
    """
    try:
        return dep.device_fp_for(recipient_id)
    except KeyError:
        return None


def _truth(kind: str, out: dict) -> dict:
    """What a *correct* leak check should recover, for the demo's ground truth.

    Shared by ``POST /demo/leak`` and ``GET /leakcheck/example/{kind}`` so the
    two routes cannot describe the same artefact's answer differently. They did
    once: the example route returned no truth at all, so the screen's
    "reveal what actually happened" control had nothing to reveal on the path a
    first-time reader takes (the example buttons) and something to reveal on the
    path they have to go looking for.

    This is the demo's *intention*, never evidence. It is what the pipeline is
    being asked to find, and it is worth showing beside the result precisely so
    the two can disagree in public -- see ``STATUS_SINGLE_MARK`` and the
    lopsided-splice cases, where a correct run deliberately does not name the
    collusion the generator set up.
    """
    if kind == "collusion":
        return {"colluders": out["colluders"],
                "ledger_indices": out["ledger_indices"]}
    return {"recipient_id": out["recipient_id"],
            "ledger_index": out["ledger_index"]}


def _word_diff(original: str, marked: str, limit: int = 200) -> list[dict]:
    """Positions where the mark changed a word, for display only.

    Deliberately dumb: it walks the two token streams in step and reports where
    they differ. That is only valid because marking is substitution-only and
    token-for-token -- which :meth:`ClientNode.mark_copy` guarantees and
    ``tests/test_watermark.py`` asserts. It is not the aligner and must not be
    used as one; the leak-check pipeline aligns properly.
    """
    from ..forensics.align import tokens

    a, b = tokens(original), tokens(marked)
    out = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            out.append({"position": i, "original": x, "marked": y})
            if len(out) >= limit:
                break
    return out
