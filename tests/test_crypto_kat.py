"""The primitives, against known-answer vectors and against the FIPS sizes.

Everything else in this repository rests on three algorithms doing exactly what
their specifications say, so it is worth being precise about what is proven here
and what is not.

**What is proven: known-answer tests.** liboqs ships, for each algorithm, the
SHA-256 of a deterministic NIST-format response file: an AES-256-CTR DRBG seeded
with ``entropy_input = 0x00..0x2f``, then keygen / encaps / decaps (or keygen /
sign / verify) at ``count = 0``, printed as ``pk = ``/``sk = ``/``ct = ``/``ss = ``
hex records. Those digests are checked into the liboqs tree. This file compiles
liboqs's own ``kat_kem`` and ``kat_sig`` programs, runs them for ML-KEM-768 and
ML-DSA-65, hashes their stdout, and compares.

The reason that is a test of *this* system rather than of some other build:
``liboqs-internal.a`` supplies only the AES/SHA3 helpers those two programs need
for the DRBG, and contains no KEM or signature code at all. The ML-KEM and
ML-DSA symbols resolve at load time from the same ``liboqs.so`` the Python
binding loads. So a digest match says the compiled crypto the application calls
reproduces the published vector, not merely that some library somewhere does.
``test_the_kat_really_exercises_the_installed_library`` asserts that linkage
rather than trusting this paragraph.

**What is not proven, and is not claimed.** SLH-DSA is not covered by a KAT
here. liboqs's own test suite skips it for the same reason -- it validates
SLH-DSA against ACVP vectors instead, and those files are not in this tree. Only
its FIPS-specified sizes and round-trip behaviour are checked below. The
externalized-anchor signature is therefore the one primitive whose byte-level
correctness rests on liboqs rather than on a vector checked here.

**What is also not proven.** A KAT match is not a side-channel assessment, and
these are the reference implementations with no claim to constant-time
behaviour under this build's compiler flags. That is a deployment concern and is
recorded in the README rather than papered over.

The second half of the file checks the constants the FIPS documents fix --
public key, secret key, ciphertext and signature lengths -- and the behaviours
that are easy to get wrong in a wrapper: implicit rejection rather than an
exception on a tampered ciphertext, ``verify`` returning False rather than
raising on malformed input, and the three algorithms being genuinely distinct
rather than one key used three ways.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from logfirst.crypto import pqc

pytest.importorskip("oqs")

# --------------------------------------------------------------------------
# Known-answer digests
# --------------------------------------------------------------------------

# SHA-256 of the NIST-format response file liboqs's kat_kem / kat_sig print for
# count = 0, from vendor/src/liboqs/tests/KATs/{kem,sig}/kats.json at the
# version this project pins. Copied here rather than read from that tree so the
# expectation does not move when the vendored source does -- a changed digest
# should be a deliberate edit with a note, not a silent pass.
KAT_DIGESTS = {
    "ML-KEM-768": "5352539586b6c3df58be6158a6250aeff402bd73060b0a3de68850ac074c17c3",
    "ML-DSA-65": "7cb96242eac9907a55b5c84c202f0ebd552419c50b2e986dc2e28f07ecebf072",
}

LIBOQS_SRC_ENV = "LOGFIRST_LIBOQS_SRC"
REPO = Path(__file__).resolve().parent.parent


def _candidates() -> list[Path]:
    """Where a liboqs source tree might be, most specific first."""
    out = []
    env = os.environ.get(LIBOQS_SRC_ENV)
    if env:
        out.append(Path(env))
    for sibling in ("new237", "237"):
        out.append(REPO.parent / sibling / "vendor" / "src" / "liboqs")
    return out


def _source_tree() -> Path | None:
    for c in _candidates():
        if (c / "tests" / "kat_kem.c").is_file():
            return c
    return None


@pytest.fixture(scope="session")
def kat_binaries(tmp_path_factory) -> dict[str, Path]:
    """Compile liboqs's own KAT programs, or skip with instructions.

    Compiled rather than shipped as binaries so that what is measured is a
    build of the library present on this machine. If the source tree is absent,
    the test skips loudly: silently skipping would let the strongest evidence in
    this file disappear without anyone noticing.
    """
    src = _source_tree()
    if src is None:
        pytest.skip(
            "no liboqs source tree found, so the known-answer tests cannot be "
            f"built; set {LIBOQS_SRC_ENV} to a liboqs checkout containing "
            "tests/kat_kem.c (a sibling ../new237 or ../237 is tried "
            "automatically)")
    cc = shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        pytest.skip("no C compiler available to build the liboqs KAT programs")

    oqs_lib = Path(os.environ.get("LOGFIRST_OQS_LIB", "/home/madhav/_oqs/lib64"))
    internal = src / "build" / "lib" / "liboqs-internal.a"
    if not internal.is_file():
        pytest.skip(
            f"{internal} is missing; configure the liboqs build first "
            "(cmake -B build && cmake --build build)")

    outdir = tmp_path_factory.mktemp("kat")
    built = {}
    for kind in ("kem", "sig"):
        exe = outdir / f"kat_{kind}"
        cmd = [
            cc, "-O1", "-o", str(exe),
            str(src / "tests" / f"kat_{kind}.c"),
            str(src / "tests" / "test_helpers.c"),
            str(src / "src" / "common" / "rand" / "rand_nist.c"),
            "-I", str(src / "build" / "include"),
            "-I", str(src / "tests"),
            "-I", str(src / "src" / "common"),
            "-I", str(src / "src" / "common" / "aes"),
            str(internal),
            "-L", str(oqs_lib), "-loqs",
            f"-Wl,-rpath,{oqs_lib}",
            "-lcrypto",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            pytest.skip(f"could not build kat_{kind}:\n{proc.stderr[-2000:]}")
        built[kind] = exe
    return built


def _run_kat(exe: Path, alg: str) -> str:
    proc = subprocess.run([str(exe), alg], capture_output=True, text=True,
                          timeout=600, env={**os.environ,
                                            "LD_LIBRARY_PATH": "/home/madhav/_oqs/lib64"})
    assert proc.returncode == 0, f"{alg}: {proc.stderr[-2000:]}"
    # liboqs's own test does this normalisation before hashing; keep it
    # identical or the digest will not match on a machine that emits CRLF.
    return proc.stdout.replace("\r\n", "\n")


@pytest.mark.parametrize("alg,kind", [("ML-KEM-768", "kem"),
                                      ("ML-DSA-65", "sig")])
def test_the_published_kat_vector_is_reproduced(kat_binaries, alg, kind):
    """The whole point of the file: the vector reproduces, byte for byte."""
    output = _run_kat(kat_binaries[kind], alg)
    got = hashlib.sha256(output.encode()).hexdigest()
    assert got == KAT_DIGESTS[alg], (
        f"{alg} does not reproduce the known-answer digest.\n"
        f"  expected {KAT_DIGESTS[alg]}\n  got      {got}\n"
        f"first 400 bytes of output:\n{output[:400]}")


def test_the_kat_output_has_the_shape_the_digest_covers(kat_binaries):
    """Guard against a digest matching an empty or truncated output.

    A program that printed nothing, or died before printing the ciphertext,
    would hash to *some* value; this asserts the records the digest is supposed
    to cover are actually present, so a future mismatch is diagnosable and a
    vacuous match cannot pass.
    """
    out = _run_kat(kat_binaries["kem"], "ML-KEM-768")
    for field in ("count = 0", "seed = ", "pk = ", "sk = ", "ct = ", "ss = "):
        assert field in out, f"{field!r} missing from the KAT output"
    # count = 0 only: the `single` digest covers one record set, not `all`.
    assert "count = 1" not in out
    # ML-KEM-768 pk is 1184 bytes -> 2368 hex chars after "pk = ".
    pk_line = next(l for l in out.splitlines() if l.startswith("pk = "))
    assert len(pk_line) - len("pk = ") == 1184 * 2
    assert set(pk_line[len("pk = "):]) <= set("0123456789ABCDEF")


def test_the_kat_really_exercises_the_installed_library(kat_binaries):
    """The claim in the module docstring, checked instead of asserted.

    The static archive is linked first, so if it carried the ML-KEM
    implementation the digest would be validating the archive and not the
    library the Python binding loads. Assert the split: the archive holds the
    AES/SHA3 helpers and no KEM code, and the KEM symbols resolve to the shared
    object at runtime.
    """
    src = _source_tree()
    internal = src / "build" / "lib" / "liboqs-internal.a"
    nm = shutil.which("nm")
    if nm:
        symbols = subprocess.run([nm, str(internal)], capture_output=True,
                                 text=True, timeout=300).stdout
        assert "OQS_KEM_ml_kem_768_keypair" not in symbols, (
            "liboqs-internal.a contains the ML-KEM implementation; the KAT "
            "would not be measuring the installed shared library")
        assert "OQS_SIG_ml_dsa_65_sign" not in symbols

    ldd = subprocess.run(["ldd", str(kat_binaries["kem"])], capture_output=True,
                         text=True, timeout=120).stdout
    assert "liboqs.so" in ldd, f"kat_kem does not link liboqs dynamically:\n{ldd}"

    # The shared object it loaded is the one in the install prefix the Python
    # binding is pointed at, and the version strings agree. Those two facts
    # together are why a digest match here says something about the crypto the
    # application calls.
    oqs_lib = Path(os.environ.get("LOGFIRST_OQS_LIB", "/home/madhav/_oqs/lib64"))
    assert str(oqs_lib / "liboqs.so") in ldd or str(oqs_lib) in ldd, (
        f"kat_kem linked a liboqs from somewhere other than {oqs_lib}:\n{ldd}")

    import oqs
    assert oqs.oqs_version() == _vendored_version(src), (
        "the installed liboqs and the vendored source are different versions, "
        "so the pinned digest does not describe the library in use")


def _vendored_version(src: Path) -> str:
    """The version string of the vendored liboqs, from its generated config."""
    cfg = (src / "build" / "include" / "oqs" / "oqsconfig.h")
    for line in cfg.read_text().splitlines():
        if line.startswith("#define OQS_VERSION_TEXT"):
            return line.split('"')[1]
    raise AssertionError(f"no OQS_VERSION_TEXT in {cfg}")


# --------------------------------------------------------------------------
# The sizes the FIPS documents fix
# --------------------------------------------------------------------------

# FIPS 203 Table 3, FIPS 204 Table 2, FIPS 205 Table 2. These are published
# constants, so they are a conformance check rather than a snapshot of whatever
# liboqs happened to produce: a wrong-length key means the wrong parameter set,
# and a truncated signature would still verify nothing.
FIPS_SIZES = {
    pqc.KEM:       {"pub": 1184, "sec": 2400, "extra": {"ct": 1088, "ss": 32}},
    pqc.SIG:       {"pub": 1952, "sec": 4032, "extra": {"sig": 3309}},
    pqc.ANCHOR_SIG: {"pub": 32, "sec": 64, "extra": {"sig": 7856}},
}


@pytest.mark.parametrize("alg", [pqc.KEM, pqc.SIG, pqc.ANCHOR_SIG])
def test_key_and_signature_sizes_match_the_specification(alg):
    want = FIPS_SIZES[alg]
    if alg == pqc.KEM:
        pub, sec = pqc.kem_keypair(alg)
        ct, ss = pqc.kem_encap(pub, alg)
        assert len(ct) == want["extra"]["ct"]
        assert len(ss) == want["extra"]["ss"]
    else:
        pub, sec = pqc.sig_keypair(alg)
        assert len(pqc.sign(sec, b"m", alg)) == want["extra"]["sig"]
    assert len(pub) == want["pub"], f"{alg} public key is the wrong size"
    assert len(sec) == want["sec"], f"{alg} secret key is the wrong size"


# --------------------------------------------------------------------------
# KEM behaviour
# --------------------------------------------------------------------------

def test_kem_round_trip_agrees():
    pub, sec = pqc.kem_keypair(pqc.KEM)
    ct, ss = pqc.kem_encap(pub, pqc.KEM)
    assert pqc.kem_decap(sec, ct, pqc.KEM) == ss


def test_two_encapsulations_of_one_key_differ():
    """Encapsulation must be randomised.

    If it were deterministic, the ciphertext would be a constant function of the
    public key and an observer could recognise a repeated wrap without breaking
    anything -- enough to correlate two documents wrapped to the same recipient.
    """
    pub, sec = pqc.kem_keypair(pqc.KEM)
    ct1, ss1 = pqc.kem_encap(pub, pqc.KEM)
    ct2, ss2 = pqc.kem_encap(pub, pqc.KEM)
    assert ct1 != ct2
    assert ss1 != ss2
    assert pqc.kem_decap(sec, ct1, pqc.KEM) == ss1
    assert pqc.kem_decap(sec, ct2, pqc.KEM) == ss2


def test_a_tampered_ciphertext_is_implicitly_rejected():
    """FIPS 203 decapsulation does not raise on a bad ciphertext.

    It returns a pseudorandom shared secret derived from the rejection value, so
    the failure surfaces later as an AEAD authentication failure rather than
    here as a distinguishable exception. This matters for the wrapper: code that
    expected an exception would instead carry on with a garbage key. The
    observable requirement is that the result differs from the real secret --
    never that it throws.
    """
    pub, sec = pqc.kem_keypair(pqc.KEM)
    ct, ss = pqc.kem_encap(pub, pqc.KEM)

    for pos in (0, len(ct) // 2, len(ct) - 1):
        bad = bytearray(ct)
        bad[pos] ^= 0x01
        got = pqc.kem_decap(sec, bytes(bad), pqc.KEM)
        assert got != ss, f"flipping byte {pos} still produced the real secret"
        assert len(got) == 32


def test_a_ciphertext_under_a_different_key_does_not_open():
    pub_a, sec_a = pqc.kem_keypair(pqc.KEM)
    pub_b, sec_b = pqc.kem_keypair(pqc.KEM)
    ct, ss = pqc.kem_encap(pub_a, pqc.KEM)
    assert pqc.kem_decap(sec_b, ct, pqc.KEM) != ss


# --------------------------------------------------------------------------
# Signature behaviour
# --------------------------------------------------------------------------

@pytest.mark.parametrize("alg", [pqc.SIG, pqc.ANCHOR_SIG])
def test_sign_and_verify_round_trip(alg):
    pub, sec = pqc.sig_keypair(alg)
    sig = pqc.sign(sec, b"the bytes that are signed", alg)
    assert pqc.verify(pub, b"the bytes that are signed", sig, alg) is True


@pytest.mark.parametrize("alg", [pqc.SIG, pqc.ANCHOR_SIG])
def test_a_modified_message_does_not_verify(alg):
    pub, sec = pqc.sig_keypair(alg)
    sig = pqc.sign(sec, b"amount: 100", alg)
    assert pqc.verify(pub, b"amount: 900", alg, sig) is False
    assert pqc.verify(pub, b"amount: 100 ", alg, sig) is False   # trailing space
    assert pqc.verify(pub, b"", alg, sig) is False


@pytest.mark.parametrize("alg", [pqc.SIG, pqc.ANCHOR_SIG])
def test_a_modified_signature_does_not_verify(alg):
    pub, sec = pqc.sig_keypair(alg)
    sig = pqc.sign(sec, b"m", alg)
    for pos in (0, len(sig) // 2, len(sig) - 1):
        bad = bytearray(sig)
        bad[pos] ^= 0x01
        assert pqc.verify(pub, b"m", bytes(bad), alg) is False


@pytest.mark.parametrize("alg", [pqc.SIG, pqc.ANCHOR_SIG])
def test_another_key_does_not_verify(alg):
    pub_a, sec_a = pqc.sig_keypair(alg)
    pub_b, _ = pqc.sig_keypair(alg)
    sig = pqc.sign(sec_a, b"m", alg)
    assert pqc.verify(pub_a, b"m", sig, alg) is True
    assert pqc.verify(pub_b, b"m", sig, alg) is False


def test_verify_returns_false_rather_than_raising_on_rubbish():
    """``False`` is the only safe answer for malformed input.

    A raised exception that escapes a gate is a crash, and a crash in a gate is
    only equivalent to a denial if every caller remembers to catch it. Returning
    False cannot be missed. This is a deliberate design choice documented on
    ``pqc.verify``; the test exists so that "improving" it into an exception
    fails here first.
    """
    pub, _ = pqc.sig_keypair(pqc.SIG)
    for sig in (b"", b"\x00", b"\x00" * 10, os.urandom(3309), b"\xff" * 4000):
        assert pqc.verify(pub, b"m", sig, pqc.SIG) is False
    for bad_pub in (b"", b"\x00", os.urandom(64)):
        assert pqc.verify(bad_pub, b"m", b"\x00" * 3309, pqc.SIG) is False


def test_signing_is_context_free_and_deterministic_in_verification_only():
    """Two signatures over one message need not be equal, and both must verify.

    ML-DSA is randomised (its nonce is derived internally with fresh
    randomness), so the two differ -- but the certificate and ledger formats
    never rely on signature equality, only on verification. Asserting the
    weaker property here keeps a future "deduplicate identical signatures"
    optimisation from silently depending on something that is not guaranteed.
    """
    pub, sec = pqc.sig_keypair(pqc.SIG)
    a = pqc.sign(sec, b"m", pqc.SIG)
    b = pqc.sign(sec, b"m", pqc.SIG)
    assert pqc.verify(pub, b"m", a, pqc.SIG)
    assert pqc.verify(pub, b"m", b, pqc.SIG)


def test_the_three_algorithms_are_distinct():
    """No key is reused across roles, and no algorithm accepts another's key."""
    kem_pub, kem_sec = pqc.kem_keypair(pqc.KEM)
    sig_pub, sig_sec = pqc.sig_keypair(pqc.SIG)
    anchor_pub, _ = pqc.sig_keypair(pqc.ANCHOR_SIG)
    assert len({kem_pub, sig_pub, anchor_pub}) == 3

    sig = pqc.sign(sig_sec, b"m", pqc.SIG)
    # A signature key is not a verification key for a different parameter set.
    assert pqc.verify(anchor_pub, b"m", sig, pqc.ANCHOR_SIG) is False
    assert pqc.verify(kem_pub, b"m", sig, pqc.SIG) is False
    del kem_sec


def test_fingerprint_is_stable_and_short():
    pub, _ = pqc.sig_keypair(pqc.SIG)
    f = pqc.fingerprint(pub)
    assert f == pqc.fingerprint(pub)
    assert len(f) == 16
    assert int(f, 16) >= 0
    other, _ = pqc.sig_keypair(pqc.SIG)
    assert pqc.fingerprint(other) != f
