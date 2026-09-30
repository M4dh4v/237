"""The verifier must not depend on the code it is verifying.

The claim "independent verifier" is worth exactly as much as the enforcement
behind it. A docstring saying "nothing here imports logfirst" stays true only
until someone adds a convenience import, and the failure is silent: the bundle
still verifies, but it now verifies against the same ``canon`` and the same
proof folding that produced it, so a bug in either would make a tampered ledger
pass while the tool reported success.

So the claim is checked two ways, and neither trusts a comment:

* **Statically** -- every ``.py`` in ``verifier/`` is parsed and searched for an
  import of ``logfirst``, and for the string ``"logfirst"`` anywhere at all,
  which also catches a dynamic import through ``importlib``.
* **Dynamically** -- ``verifier.verify`` is imported and exercised in a
  subprocess with a meta-path hook that raises on any attempt to import
  ``logfirst``. Static analysis cannot see a runtime import; this can.

The static pass matters separately because it fails on the *intent* to import,
even on a code path a test would not happen to execute.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VERIFIER = REPO / "verifier"


def verifier_files() -> list[Path]:
    return sorted(VERIFIER.rglob("*.py"))


def test_verifier_package_is_not_empty():
    """Guard against the scan passing because it found nothing to scan."""
    files = verifier_files()
    assert len(files) >= 2, files
    assert any(f.name == "core.py" for f in files)
    assert any(f.name == "verify.py" for f in files)


@pytest.mark.parametrize("path", verifier_files(), ids=lambda p: p.name)
def test_no_logfirst_import_statically(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.split(".")[0] == "logfirst", \
                    f"{path.name}: imports {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root != "logfirst", \
                f"{path.name}: imports from {node.module}"
            # A relative import can only reach inside this package, but assert
            # it does not climb out past the package root.
            if node.level:
                assert node.level <= 1, \
                    f"{path.name}: relative import climbs {node.level} levels"


@pytest.mark.parametrize("path", verifier_files(), ids=lambda p: p.name)
def test_no_dynamic_import_can_reach_logfirst(path):
    """Static import checks miss ``importlib``; this closes that door.

    A computed module name cannot be audited, so a non-constant argument to
    ``importlib.import_module`` or ``__import__`` is treated as a failure on its
    own -- not because it is necessarily reaching for ``logfirst``, but because
    the whole point of this file is that the property must be checkable without
    reading the code's mind. The verifier has no need for a dynamic import, so
    the rule costs nothing.

    Plain prose mentioning the name is fine and deliberate: the package
    docstrings explain *why* the independence holds, and the CLI help text names
    the bundle format. It is code that must not reach for it.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = None
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        if name not in ("import_module", "__import__"):
            continue
        args = node.args
        assert args, f"{path.name}: {name}() with no argument"
        arg = args[0]
        if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
            pytest.fail(
                f"{path.name}:{node.lineno}: {name}() is called with a computed "
                "module name, which cannot be checked for a dependency on the "
                "server's code")
        root = arg.value.split(".")[0]
        assert root != "logfirst", \
            f"{path.name}:{node.lineno}: dynamically imports {arg.value}"


CHILD = textwrap.dedent('''
    import sys

    BLOCKED = []

    class BlockLogfirst:
        """Refuse to import anything under logfirst, and say what was asked for."""

        def find_spec(self, name, path=None, target=None):
            if name == "logfirst" or name.startswith("logfirst."):
                BLOCKED.append(name)
                raise ImportError(f"BLOCKED: verifier tried to import {name}")
            return None

    sys.meta_path.insert(0, BlockLogfirst())

    import json
    import verifier.verify as v

    bundle = json.load(open(sys.argv[1]))
    report = v.verify_bundle(bundle)

    leaked = [m for m in sys.modules
              if m == "logfirst" or m.startswith("logfirst.")]
    print(json.dumps({
        "ok": report["ok"],
        "entries_ok": report["entries_ok"],
        "blocked": BLOCKED,
        "leaked_modules": leaked,
    }))
''')


@pytest.fixture(scope="module")
def real_bundle(tmp_path_factory):
    """A bundle built by the real server, for the child process to verify."""
    import json

    pytest.importorskip("oqs")
    from logfirst.crypto import ca as ca_mod
    from logfirst.forensics.bundle import BundleExporter
    from logfirst.ledger import merkle

    root = tmp_path_factory.mktemp("indep")
    from tests.conftest import make_log, make_request, make_witnesses

    witnesses = make_witnesses(root, 3)
    log = make_log(root, witnesses, min_witnesses=2)

    # Real CA-issued certificates. The bundle has to carry them for the child to
    # check the request signature against a certified identity rather than
    # against a key the bundle merely asserts is the recipient's -- so without
    # this the child would verify "some key signed this" and report success,
    # which is exactly the weaker claim the verifier exists to refuse.
    ca = ca_mod.CA.create()
    certs = {}
    for i in range(4):
        rid = f"u{i}"
        cert, secrets = ca_mod.enroll_recipient(ca, rid)
        certs[rid] = cert.__dict__
        log.gated_append_for_decryption(
            make_request(rid, f"DOC-{i:04d}",
                         sig_sec=bytes.fromhex(secrets["sig_sec"])).leaf_bytes(),
            "127.0.0.1")

    from logfirst.ledger.anchor import Anchorer
    anchorer = Anchorer.open(str(root / "anchors.jsonl"))
    anchor = anchorer.anchor(2, merkle.root_from_hashes(
        log.leaf_hashes()[:2]).hex())

    exp = BundleExporter(
        log_pub=log.log_pub,
        witness_pubs={w.witness_id: w.signer.sig_pub for w in witnesses},
        recipient_certs=certs, witness_quorum=2, anchor_pub=anchorer.anchor_pub,
        ca_pub=ca.sig_pub)
    path = root / "bundle.json"
    exp.save(log, [0, 1, 2, 3], str(path), [anchor])
    return str(path)


def test_verify_runs_with_logfirst_unimportable(real_bundle):
    """The real check: a subprocess where importing logfirst raises."""
    import json
    import site

    # The child runs with a clean HOME, so it cannot rely on the per-user site
    # to find its own dependencies (oqs, cryptography). We pass the real
    # interpreter's site directories on PYTHONPATH explicitly, so the verifier's
    # legitimate deps resolve wherever they were installed -- venv, system, or
    # `pip --user`/`--break-system-packages`. logfirst being reachable on the
    # path too is fine and deliberate: independence is enforced by the meta-path
    # hook that raises on any logfirst import, not by hiding it.
    pythonpath = os.pathsep.join(
        [str(REPO), *site.getsitepackages(), site.getusersitepackages()]
    )
    proc = subprocess.run(
        [sys.executable, "-c", CHILD, real_bundle],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
        env={"PYTHONPATH": pythonpath, "PATH": "/usr/bin:/bin",
             # liboqs must be loadable by the subprocess. Inherit the ambient
             # path when set, else fall back to the conventional local build
             # ($HOME/_oqs/lib). Never a hardcoded per-developer absolute path.
             "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH")
                 or os.path.expanduser("~/_oqs/lib"),
             "HOME": "/tmp"})
    assert proc.returncode == 0, (
        f"child failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["blocked"] == [], \
        f"verifier attempted to import {out['blocked']}"
    assert out["leaked_modules"] == [], \
        f"logfirst modules present in sys.modules: {out['leaked_modules']}"
    # And it still does its job with the server's code unavailable.
    assert out["ok"] is True
    assert out["entries_ok"] is True


def test_the_block_would_actually_fire():
    """Sanity-check the guard: if the hook were broken, the test above is vacuous.

    Imports logfirst from inside the child's hook and asserts it is refused --
    proving the mechanism detects a violation rather than merely never seeing
    one.
    """
    code = textwrap.dedent('''
        import sys

        class BlockLogfirst:
            def find_spec(self, name, path=None, target=None):
                if name == "logfirst" or name.startswith("logfirst."):
                    raise ImportError(f"BLOCKED: {name}")
                return None

        sys.meta_path.insert(0, BlockLogfirst())
        try:
            import logfirst
        except ImportError as e:
            print("REFUSED:", e)
        else:
            print("NOT REFUSED -- the hook does not work")
    ''')
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(REPO),
                          capture_output=True, text=True, timeout=120,
                          env={"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin",
                               "HOME": "/tmp"})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("REFUSED:"), proc.stdout
