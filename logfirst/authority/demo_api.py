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
import io
import os
import re
from datetime import datetime, timezone

from fastapi import File, Form, HTTPException, Request, Response, UploadFile
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


class ComposeBody(BaseModel):
    title: str | None = None
    body: str


class RecipientCreateBody(BaseModel):
    display_name: str
    role: str = "recipient"


class CertificateBody(BaseModel):
    # A "finding" is a ledger session the investigator attributed a leak to; the
    # front end passes back the ledger index it was given. There is no separate
    # finding store, so the index *is* the identifier -- the certificate is built
    # straight from the ledger, which is the only thing that could be evidence.
    finding_id: int | str


def _b64_image(data: str) -> bytes:
    """Decode a browser data URL or a bare base64 payload."""
    if "," in data[:64] and data.lstrip().startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        return base64.b64decode(data, validate=True)
    except Exception as e:
        raise HTTPException(400, f"image_b64 is not valid base64: {e}") from e


_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp")
_TEXT_EXTS = (".txt", ".md", ".markdown", ".text", ".csv", ".log")

# Tesseract reads text best at ~300 DPI with a tall, high-contrast glyph. A
# screenshot is ~96 DPI and its text is often 12-16px, which is where the merge/
# split errors this pipeline has to absorb come from. Upscaling to this width
# before OCR is the single biggest quality win and costs nothing downstream.
# ponytail: fixed target width, 3x cap. Expose via env if a deployment scans
# images of wildly different sizes.
_OCR_TARGET_WIDTH = 2000
_OCR_MAX_SCALE = 3.0


def _prep_for_ocr(img):
    """Grayscale + upscale a screenshot so OCR reads it cleanly.

    A pure pixel funnel in front of the *unchanged* OCR path -- it changes how
    the image is read, never what the watermark or ledger do with the text. The
    same characters come out, just more of them correct: a legibly-sized,
    high-contrast glyph is segmented far more reliably, so fewer carrier slots
    are lost to word merges.
    """
    from PIL import Image, ImageOps

    img = img.convert("L")  # tesseract binarises internally; give it clean gray
    if img.width < _OCR_TARGET_WIDTH:
        scale = min(_OCR_MAX_SCALE, _OCR_TARGET_WIDTH / img.width)
        img = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)
    return ImageOps.autocontrast(img)


def _ocr_image(data: bytes) -> str:
    """Decode image bytes, prep them, and OCR via the unchanged watermark path."""
    from ..watermark import ocr
    try:
        return ocr.image_to_text(_prep_for_ocr(ocr.bytes_to_image(data)))
    except Exception as e:                             # OCRError / PIL decode
        raise HTTPException(400, f"could not read the image: {e}") from e


def _extract_document(filename: str, content_type: str | None,
                      data: bytes) -> tuple[str, list[dict]]:
    """Turn an uploaded file into text, page by page, using existing paths only.

    This is the whole of what the upload adapters add: an input funnel in front
    of the *unchanged* seal and forensics pipelines. It does no cryptography and
    no analysis; it decides how to get characters out of a file and says, per
    page, how it did it. Three ways in, and nothing else:

    - text / markdown  -> decode UTF-8 (the bytes pass through untouched).
    - image            -> the existing tesseract OCR path.
    - PDF              -> the text layer, via ``pypdf``, one page at a time. A
      page with no text layer is reported as ``"none"`` rather than guessed at:
      this build has no PDF rasteriser, so a scanned page has no honest text and
      saying so is the point.

    Returns ``(text, pages)`` where ``pages`` is a list of
    ``{"page", "extraction", "chars"}`` for the per-page status the trace tool
    shows. ``text`` is the concatenation a downstream stage sees.
    """
    name = (filename or "").lower()
    ctype = (content_type or "").lower()

    is_pdf = name.endswith(".pdf") or "pdf" in ctype
    is_image = name.endswith(_IMAGE_EXTS) or ctype.startswith("image/")
    is_text = name.endswith(_TEXT_EXTS) or ctype.startswith("text/")

    if is_pdf:
        try:
            from pypdf import PdfReader
        except ImportError as e:                       # pragma: no cover
            raise HTTPException(
                400, "pypdf is not installed; cannot read PDFs in this "
                     "build") from e
        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception as e:
            raise HTTPException(400, f"could not read the PDF: {e}") from e
        parts, pages = [], []
        for i, page in enumerate(reader.pages, start=1):
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                parts.append(t)
                pages.append({"page": i, "extraction": "text-layer",
                              "chars": len(t)})
            else:
                # No text layer, and no rasteriser here to OCR it.
                pages.append({"page": i, "extraction": "none", "chars": 0})
        return "\n\n".join(parts), pages

    if is_image:
        text = _ocr_image(data)
        return text, [{"page": 1, "extraction": "ocr", "chars": len(text)}]

    # Text, markdown, or anything we can decode. `is_text` is a hint; a file with
    # no useful extension still decodes if it is really text, and 400s if it is
    # binary we have no reader for.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(
            400, f"unsupported file: not a PDF or image, and not UTF-8 text "
                 f"({e})") from e
    return text, [{"page": 1, "extraction": "text", "chars": len(text)}]


def _slug(s: str) -> str:
    """A recipient id from a display name: lowercase, ascii-ish, no surprises."""
    out = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return out[:32] or "recipient"


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
        ocr_text = None
        if body.image_b64:
            # OCR here in the glue -- with the screenshot prep -- rather than
            # handing raw bytes to investigate(), so the prep applies to pasted
            # and dropped images too, not only uploads. investigate() then runs
            # on text exactly as it does for a pasted passage; its own module
            # stays untouched.
            ocr_text = _ocr_image(_b64_image(body.image_b64))
            text = ocr_text
        if not text.strip():
            raise HTTPException(400, "nothing to check: pass text or image_b64")
        inv = scenario.investigator().investigate(leaked_text=text)
        result = inv.as_dict()
        result["simulated"] = list(SIMULATED)
        if ocr_text is not None:
            # What OCR actually read, so the analyst can see why a mark did or
            # did not survive. Word order is not preserved (see watermark/ocr.py)
            # -- labelled as read-text, never presented as the verbatim leak.
            result["ocr_text"] = ocr_text
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

    # -- the demo sandbox reset --------------------------------------------
    #
    # The one control that takes the demo back to a clean state. It is NOT an
    # authority capability and must never read as one: the whole thesis is that
    # no single administrator can rewrite the witnessed record. What this does
    # is restart the *operator's own demo instance* from seed -- new keys, fresh
    # witnesses, an empty ledger. It cannot delete a leaf, and it does not exist
    # on a production-shaped run (no scenario -> none of this surface at all).
    #
    # Mechanism: drop a one-shot sentinel the launcher reads on boot, then ask
    # the ASGI server to shut down. `serve()`'s own `finally` reaps the witness
    # processes (a hard exit here would orphan them and leave 9101+ held); the
    # supervisor restarts the process; the sentinel makes that restart build
    # `fresh=True`. Nothing on this path touches the ledger module.
    #
    # The handle is published by the launcher and is present only when the
    # process is supervised and can actually be brought back. Without it -- a
    # foreground `--serve`, or run.sh -- stopping the server would just leave
    # the console dark, so we refuse and hand over the command instead.

    @app.post("/demo/admin/reset")
    def admin_reset(request: Request):
        restart = getattr(request.app.state, "sakshya_restart", None)
        if restart is None:
            return {
                "ok": False, "supervised": False, "rebuilding": False,
                "command": "python scripts/demo.py --serve --fresh",
                "note": (
                    "This instance is not running under a supervisor, so it "
                    "cannot restart itself. Stop it and start it again with "
                    "--fresh to reseed the sandbox. This is a reset of the "
                    "local demo instance, not a capability of the authority: "
                    "no single administrator can clear a real deployment's "
                    "witnessed ledger, and nothing here does."
                ),
            }
        sentinel = scenario.dep.path("RESET_REQUESTED")
        with open(sentinel, "w", encoding="utf-8") as fh:
            fh.write("reset requested via /demo/admin/reset\n")
        restart()
        return {
            "ok": True, "supervised": True, "rebuilding": True,
            "note": (
                "Rebuilding this demo sandbox from seed: new keys, fresh "
                "witnesses, an empty ledger, the curated documents back. This "
                "restarts the local demo instance. It is not an authority "
                "capability -- no single administrator can clear a real "
                "deployment's witnessed ledger."
            ),
        }

    # -- source ingestion: upload / compose / capacity ---------------------
    #
    # These add no pipeline: an uploaded or composed body is registered as a
    # sealable document the exact same way the curated corpus is, by living in
    # `scenario.docs`. `/demo/distribute` seals it and the investigator aligns
    # against it with no knowledge that it did not come from the corpus. The
    # only new code is getting text out of a file (`_extract_document`) and
    # reading the capacity number the watermark planner already computes.

    def _capacity(text: str) -> dict:
        from ..watermark import linguistic, payload

        cfg = dep.tardos_config()
        plan = payload.plan_for_document(
            linguistic.slot_count(text), len(cfg["users"]),
            cfg["colluders"], cfg["eps"])
        # `strength` is the planner's own word -- "formal" / "ranking-only" /
        # "none" -- never softened. It is the honest ceiling on what an
        # attribution from this document could claim.
        return {"positions": plan["tardos_bits"],
                "needed": plan["tardos_required"],
                "strength": plan["guarantee"]}

    def _register_source(text: str, classification: str = "SECRET") -> dict:
        from ..watermark import linguistic

        if not text.strip():
            raise HTTPException(400, "no text to seal: the document is empty")
        doc_id = "SRC-" + os.urandom(4).hex().upper()
        while any(d["doc_id"] == doc_id for d in scenario.docs):
            doc_id = "SRC-" + os.urandom(4).hex().upper()
        scenario.docs.append({
            "doc_id": doc_id, "text": text, "classification": classification,
            "slots": linguistic.slot_count(text),
            "words": len(text.split()),
        })
        return {"docId": doc_id, "preview": text[:280],
                "capacity": _capacity(text)}

    @app.post("/demo/source/upload")
    async def source_upload(file: UploadFile = File(...),
                            title: str | None = Form(None)):
        """Seal an uploaded file: extract its text, register it as a document."""
        data = await file.read()
        text, _pages = _extract_document(file.filename, file.content_type, data)
        if not text.strip():
            raise HTTPException(
                400, "no extractable text: an image-only PDF cannot be sealed "
                     "in this build (no rasteriser to OCR its pages)")
        return _register_source(text)

    @app.post("/demo/source/compose")
    def source_compose(body: ComposeBody):
        """Register a document typed in-app. Same path as an upload."""
        text = body.body
        if body.title and body.title.strip():
            text = f"{body.title.strip()}\n\n{body.body}"
        return _register_source(text)

    @app.get("/demo/source/{doc_id}/capacity")
    def source_capacity(doc_id: str):
        """Watermark capacity for a chosen document, from the existing planner."""
        try:
            doc = scenario.doc(doc_id)
        except KeyError:
            raise HTTPException(404, f"no such document {doc_id}")
        return _capacity(doc["text"])

    # -- recipient enrolment from the UI -----------------------------------

    @app.post("/demo/admin/recipients/create")
    def admin_recipients_create(body: RecipientCreateBody):
        """Enrol a new recipient via the existing CA + store path.

        Companion to revoke/reinstate. The keypair is minted by the *existing*
        `ca.enroll_recipient` (real ML-DSA); this route does no cryptography of
        its own. `sync_store` is the same step the deployment uses at boot to
        carry the CA's certificate into the authority's store.
        """
        if not body.display_name.strip():
            raise HTTPException(400, "display_name is required")
        rid = _slug(body.display_name)
        existing = dep.recipients()
        if rid in existing:
            rid = f"{rid}-{os.urandom(2).hex()}"
        dep.add_recipient(rid, role=body.role)
        dep.sync_store(scenario.store)
        cert = dep.cert_for(rid)
        fingerprint = hashlib.sha256(bytes.fromhex(cert.sig_pub)).hexdigest()
        return {
            "recipientId": rid,
            "displayName": body.display_name,
            "role": body.role,
            "fingerprint": fingerprint,
            "status": "active",
            # Stated, not hidden: the Tardos user order is frozen at deploy so
            # marker and investigator agree on "user N". A recipient enrolled
            # afterwards can be sent and can open documents, but is not in that
            # order, so it is out of scope for collusion *indexing*.
            "note": "Enrolled with a fresh ML-DSA keypair. Not added to the "
                    "frozen Tardos user order, so it is outside collusion "
                    "indexing until a redeploy rebuilds that order.",
        }

    # -- trace tool: check a whole uploaded document -----------------------

    @app.post("/leakcheck/upload")
    async def leakcheck_upload(file: UploadFile = File(...)):
        """Run the *unchanged* forensic pipeline over an uploaded document.

        Text is extracted page by page (text layer / OCR / passthrough) and the
        concatenation is handed to the same `Investigator.investigate` the
        `/leakcheck` route uses. The response is that route's shape plus a
        per-page `pages` list; nothing about the result is summarised here.
        """
        data = await file.read()
        text, pages = _extract_document(file.filename, file.content_type, data)
        inv = scenario.investigator().investigate(leaked_text=text)
        result = inv.as_dict()
        result["simulated"] = list(SIMULATED)
        result["pages"] = pages
        return result

    # -- certificate: an independently-verifiable evidence bundle ----------

    @app.post("/evidence/certificate")
    def evidence_certificate(body: CertificateBody):
        """Build the evidence bundle for a finding (a ledger session index).

        Presentation adapter over the *existing* `BundleExporter`: it produces
        the same JSON `verifier/` checks, with no new proof logic. The
        human-readable Pramāṇapatra PDF is a later presentation step; the JSON is
        the load-bearing artefact and is returned now.
        """
        from ..forensics.bundle import BundleExporter, ExportError

        try:
            idx = int(body.finding_id)
        except (TypeError, ValueError):
            raise HTTPException(
                400, f"finding_id must be a ledger index, got "
                     f"{body.finding_id!r}")
        exporter = BundleExporter.from_deployment(dep, scenario.log)
        anchors = dep.anchorer().records() if dep.anchorer() is not None else None
        try:
            bundle = exporter.bundle(scenario.log, [idx], anchors)
        except ExportError as e:
            raise HTTPException(400, str(e)) from e
        return {
            "pdf": None,
            "json": bundle,
            "note": "This JSON is the independently-verifiable evidence bundle; "
                    "check it with the standalone verifier/. A human-readable "
                    "Pramāṇapatra PDF is a later presentation step.",
        }


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
