"""A standalone verifier for ledger evidence bundles.

Nothing in this package imports ``logfirst``. Run it against a bundle produced
by the authority and it will re-derive every claim from the public outputs
alone -- canonicalising the leaf, folding the Merkle proofs, and checking each
signature with its own copy of the code:

    python -m verifier.verify bundle.json

Exit status is 0 only when every entry verifies *and* the history is consistent
with an externalized root; see ``verifier.verify`` for what the other codes mean.

The public names are exposed lazily (PEP 562) rather than imported here, so that
``python -m verifier.verify`` does not import the module twice and warn about it.
"""

from .core import canon, verify_inclusion, verify_consistency

__all__ = ["verify_bundle", "BundleError", "canon", "verify_inclusion",
           "verify_consistency"]


def __getattr__(name):
    if name in ("verify_bundle", "BundleError"):
        from . import verify
        return getattr(verify, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
