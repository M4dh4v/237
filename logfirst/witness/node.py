"""The witness node as a standalone HTTP service.

This runs as its **own OS process**, with its own key file, listening on its own
port. That is the whole point: the authority reaches it over a socket and cannot
produce its signature without asking. In the older in-process design the
"witnesses" were three keypairs in the authority's own memory and co-signing was
a method call -- which meant an operator who controlled the authority controlled
every witness, and the quorum arithmetic implied an independence that did not
exist.

Running three processes on one host is a real improvement and still not the
whole story: they share a kernel, a filesystem and an administrator. It defends
against a *compromised authority process*, not against someone with root on the
box. Say that out loud in the demo rather than letting "3 of 3 witnesses agreed"
imply more than it does.

Run one with::

    python -m logfirst.witness.node --id w1 --port 9101 --state demo/w1.json
"""

from __future__ import annotations

import argparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..crypto import pqc
from .signer import CosignRefused, WitnessSigner


class CosignBody(BaseModel):
    tree_size: int
    root_hash: str
    # The log's timestamp for this head. Required, because the witness signs
    # the same STH.tbs() the log signed -- see WitnessSigner.cosign.
    timestamp: str
    consistency_proof: list[str] = []
    # Carried for the demo's benefit so the UI can say *why* a witness was
    # asked; the witness itself never trusts these.
    note: str | None = None


def build_app(signer: WitnessSigner) -> FastAPI:
    app = FastAPI(title=f"logfirst witness {signer.witness_id}", version="1.0")

    @app.get("/health")
    def health():
        return {"ok": True, "witness_id": signer.witness_id,
                "max_size": signer.max_size}

    @app.get("/pubkey")
    def pubkey():
        return {"witness_id": signer.witness_id, "pub": signer.sig_pub.hex(),
                "sig_alg": pqc.SIG}

    @app.post("/cosign")
    def cosign(body: CosignBody):
        try:
            return signer.cosign(body.tree_size, body.root_hash, body.timestamp,
                                 body.consistency_proof)
        except CosignRefused as e:
            # 409, not 500: this is a deliberate refusal, and the caller must
            # treat it as "no key for you", not as "try again".
            raise HTTPException(status_code=409, detail=str(e))

    @app.get("/history")
    def history():
        return signer.history()

    return app


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Run one witness node.")
    ap.add_argument("--id", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--state", required=True, help="path to this witness's key/state file")
    args = ap.parse_args(argv)

    import uvicorn
    signer = WitnessSigner.open(args.id, args.state)
    uvicorn.run(build_app(signer), host=args.host, port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
