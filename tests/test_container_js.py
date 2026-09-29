"""The browser's container parser, checked against Python's on real containers.

``web/src/container.js`` is a second implementation of ``logfirst/sealed.py``,
and a second implementation of a binary format is a liability: the two drift, and
the one that drifts is the one a reader actually looks at. This file is what
keeps them together. It parses genuine containers produced by the Python side
with the JavaScript parser, under Node, and asserts the two agree -- then does
the same for the malformed inputs, which must raise on **both** sides.

Two notes on how it runs.

* The magic is asserted here to be seven bytes. An earlier draft of the JS file
  took a prose summary's word that it was eight, which would have made the parser
  reject every real container with a message about a bad magic string -- a total
  failure that reads like a corrupt file. Hence a test for the constant itself.
* The containers are written to disk and read by the Node process rather than
  piped. Reading them in Node means exercising the same Buffer-to-ArrayBuffer
  conversion a browser's ``FileReader`` result needs, and that conversion is
  where an off-by-one in ``byteOffset`` silently hashes the wrong bytes.

Skipped, not failed, when ``node`` is not installed: this is the only test in the
suite that needs it, and its absence says nothing about the project.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from logfirst import sealed as sealed_mod
from logfirst.crypto import ca as ca_mod
from logfirst.crypto import onetime, pqc

pytest.importorskip("fastapi")

NODE = shutil.which("node")
CONTAINER_JS = (Path(__file__).resolve().parents[1] / "web" / "src" / "container.js")

pytestmark = pytest.mark.skipif(
    NODE is None, reason="node is not installed; the JS parser cannot be run")

# Dispatches on argv and prints one JSON object. Kept in the test file rather
# than on disk in web/ so it cannot rot into something the app depends on: it is
# scaffolding for this test and nothing else loads it.
RUNNER = r"""
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

const [mode, ...rest] = process.argv.slice(2)
const mod = await import(pathToFileURL(process.env.LF_CONTAINER_JS).href)

// A Node Buffer is a view onto a pooled ArrayBuffer, so `buf.buffer` is very
// often larger than the file and starts at the wrong offset. Slicing by
// byteOffset/byteLength is the difference between hashing the file and hashing
// whatever happened to be in the pool beside it.
function toArrayBuffer(buf) {
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)
}

let out
try {
  if (mode === 'parse' || mode === 'sha256') {
    const bytes = toArrayBuffer(readFileSync(rest[0]))
    if (mode === 'parse') {
      const p = mod.parseContainer(bytes)
      out = { ok: true, header: p.header, headerBytes: p.headerBytes,
              ciphertextBytes: p.ciphertextBytes, totalBytes: p.totalBytes }
    } else {
      out = { ok: true, hex: await mod.sha256Hex(bytes) }
    }
  } else if (mode === 'compare') {
    out = { ok: true, disagreements: mod.compareLabels(
      JSON.parse(readFileSync(rest[0], 'utf8')),
      JSON.parse(readFileSync(rest[1], 'utf8'))) }
  } else if (mode === 'constants') {
    // Reported from inside the module so the assertion is about what the module
    // actually holds, not about a copy of it in the test.
    out = { ok: true, agreedFields: mod.AGREED_FIELDS,
            errorName: new mod.ContainerError('x').name }
  } else {
    out = { ok: false, error: `unknown mode ${mode}` }
  }
} catch (e) {
  out = { ok: false, error: e.message, name: e.name }
}
process.stdout.write(JSON.stringify(out))
"""


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    """The Node runner, invoked with the module path in the environment."""
    path = tmp_path_factory.mktemp("js") / "runner.mjs"
    path.write_text(RUNNER, encoding="utf-8")

    def run(mode: str, *args: str) -> dict:
        proc = subprocess.run(
            [NODE, str(path), mode, *args],
            capture_output=True, text=True, timeout=60,
            env={"LF_CONTAINER_JS": str(CONTAINER_JS), "PATH": "/usr/bin:/bin"},
        )
        assert proc.returncode == 0, (
            f"the node runner exited {proc.returncode}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        return json.loads(proc.stdout)

    return run


@pytest.fixture(scope="module")
def container(tmp_path_factory):
    """A genuine sealed container, and the manifest sealed inside it.

    Built through the real sealing path and then genuinely decrypted, rather
    than with a hand-written manifest: the comparison these tests exercise is
    between a real unauthenticated header and the real authenticated manifest,
    and a manifest this file made up could agree with a wrong header and still
    look like a pass.
    """
    server_kem_pub, server_kem_sec = pqc.kem_keypair(pqc.KEM)
    text = "The quarterly annex records no unusual activity. " * 40
    pdf = b"%PDF-1.4\n% not a real pdf, but the bytes are sealed as-is\n"
    package = ca_mod.encrypt_framed_payload(
        text, pdf, "DOC-0000", "internal", server_kem_pub,
        extra_manifest={"created": "2026-01-01T00:00:00+00:00",
                        "font": "DejaVuSans", "pages": 2})
    blob = sealed_mod.pack(package)
    path = tmp_path_factory.mktemp("containers") / "DOC-0000.lfdoc"
    path.write_bytes(blob)

    key = onetime.unseal_content_key(server_kem_sec, package["key_envelope"])
    manifest = ca_mod.open_payload(package, key)["manifest"]
    return SimpleNamespace(path=path, blob=blob,
                           header=sealed_mod.unpack(blob)["header"],
                           manifest=manifest)


# ==========================================================================
# The constant that nearly shipped wrong
# ==========================================================================

def test_the_container_magic_is_seven_bytes():
    """``b"LFDOC\\x00\\x01"``. Two implementations have to agree on this, and a
    prose description of it said eight while listing seven values.

    Pinned explicitly because the JS file derives its magic length from the
    array, so if someone "fixes" the JS constant to match a wrong note here,
    this is what catches it -- the failure would otherwise be that every genuine
    container is rejected by the browser as a bad magic string.
    """
    assert len(sealed_mod.CONTAINER_MAGIC) == 7
    assert sealed_mod.CONTAINER_MAGIC == bytes([0x4C, 0x46, 0x44, 0x4F, 0x43,
                                               0x00, 0x01])


def test_the_js_module_holds_the_same_agreed_fields(runner):
    """The field list both sides compare over, read out of the module itself.

    A field added to one list and not the other means a tampered header passes
    the check in one implementation and fails in the other -- which is worse than
    either, because the answer then depends on which tool a person used.
    """
    got = runner("constants")
    assert got["ok"] is True, got
    assert got["agreedFields"] == list(sealed_mod.AGREED_FIELDS)
    assert got["errorName"] == "ContainerError"


# ==========================================================================
# They agree on real containers
# ==========================================================================

def test_the_js_parser_reads_a_real_container_exactly_as_python_does(
        runner, container):
    """Field for field, against ``sealed.unpack``.

    Compared against the Python parse of the same bytes rather than against a
    hand-written expectation, so this cannot pass by both sides being wrong in
    the same way as an old test.
    """
    py = sealed_mod.unpack(container.blob)
    js = runner("parse", str(container.path))

    assert js["ok"] is True, js
    assert js["header"] == py["header"], (
        "the two parsers disagree about a real container's header")
    assert js["ciphertextBytes"] == len(py["ciphertext"])
    assert js["totalBytes"] == len(container.blob)
    assert js["headerBytes"] + js["ciphertextBytes"] + 7 + 4 == len(container.blob)


def test_the_js_describe_matches_the_python_describe(runner, container):
    """``describe`` is what the CLI prints and what the screen renders, so the
    two must be the same object, not merely both plausible."""
    js = runner("parse", str(container.path))
    assert js["header"] == sealed_mod.describe(container.blob)


def test_both_sides_hash_the_same_bytes(runner, container):
    """The hash the container screen compares against the authority.

    It is the check that stands between an edited label and a PDF from the wrong
    document, so it is worth confirming the browser and Python agree on it --
    including that the Buffer slicing above feeds ``crypto.subtle`` the file and
    nothing adjacent to it.
    """
    import hashlib

    js = runner("sha256", str(container.path))
    assert js["ok"] is True, js
    assert js["hex"] == hashlib.sha256(container.blob).hexdigest()


def test_the_two_compare_functions_agree(runner, container, tmp_path):
    """``compareLabels`` against ``sealed.compare``, over the real header and the
    real manifest that came out of decrypting the same container.

    An empty result is the expected one -- these two describe the same document,
    which is the whole point of the header being a copy of the manifest -- and
    the tamper below is what stops this passing for the wrong reason.
    """
    header = container.header
    manifest = container.manifest
    hp, mp = tmp_path / "header.json", tmp_path / "manifest.json"
    mp.write_text(json.dumps(manifest), encoding="utf-8")

    def both(h):
        hp.write_text(json.dumps(h), encoding="utf-8")
        js = runner("compare", str(hp), str(mp))
        assert js["ok"] is True, js
        assert js["disagreements"] == sealed_mod.compare(h, manifest)
        return js["disagreements"]

    assert both(header) == [], (
        "the header and the sealed manifest of a genuine container disagree, so "
        "there is nothing here that a tamper could be distinguished from")

    doctored = dict(header)
    doctored["pages"] = (header.get("pages") or 0) + 1
    assert both(doctored) == ["pages"]


@pytest.mark.parametrize("field", list(sealed_mod.AGREED_FIELDS))
def test_every_agreed_field_is_actually_compared(runner, container, tmp_path,
                                                 field):
    """Each field in the list, changed alone, must be reported by both sides.

    A field in ``AGREED_FIELDS`` that no implementation reports is a field whose
    tampering is invisible, which is the failure mode of a check that looks like
    it covers more than it does. Parametrised over the Python list, so a field
    added there is covered without anyone remembering to add a case here.
    """
    header = dict(container.header)
    original = header.get(field)
    header[field] = "tampered" if not isinstance(original, int) else original + 1

    hp, mp = tmp_path / f"h-{field}.json", tmp_path / "m.json"
    hp.write_text(json.dumps(header), encoding="utf-8")
    mp.write_text(json.dumps(container.manifest), encoding="utf-8")

    js = runner("compare", str(hp), str(mp))
    assert js["disagreements"] == sealed_mod.compare(header, container.manifest)
    assert field in js["disagreements"], (
        f"{field} is in AGREED_FIELDS but changing it is not reported")


def test_a_field_present_on_only_one_side_disagrees(runner, container, tmp_path):
    """The subtle half of ``compare``, on both sides.

    A field present in the header and absent from the manifest is a
    disagreement, not a skip: it is one side declining to be checked.
    """
    header = container.header
    manifest = {k: v for k, v in container.manifest.items() if k != "font"}

    hp = tmp_path / "h.json"
    mp = tmp_path / "m.json"
    hp.write_text(json.dumps(header), encoding="utf-8")
    mp.write_text(json.dumps(manifest), encoding="utf-8")

    js = runner("compare", str(hp), str(mp))
    assert js["disagreements"] == sealed_mod.compare(header, manifest)
    assert "font" in js["disagreements"]


# ==========================================================================
# They refuse the same things
# ==========================================================================

def _write(tmp_path, name, blob):
    p = tmp_path / name
    p.write_bytes(blob)
    return p


def _rejects_both(runner, path, blob):
    """The file must raise in Python *and* come back ok:false from Node.

    Both directions are asserted. A parser that accepts what the other rejects
    is how a malformed container gets a different verdict depending on which
    tool was used.
    """
    with pytest.raises(Exception):
        sealed_mod.unpack(blob)
    got = runner("parse", str(path))
    assert got["ok"] is False, (
        f"the JS parser accepted something Python refused: {got}")
    assert got["name"] == "ContainerError", got
    assert got["error"], "the JS parser raised with no message"


def test_both_reject_a_bad_magic(runner, tmp_path):
    """One byte of the magic changed -- which is what a file that is not a
    container at all looks like, and what a version bump looks like."""
    blob = bytearray(sealed_mod.pack(_package()))
    blob[3] ^= 0xFF
    _rejects_both(runner, _write(tmp_path, "magic.lfdoc", blob), bytes(blob))


def test_both_reject_a_file_shorter_than_the_magic(runner, tmp_path):
    blob = b"LFD"
    _rejects_both(runner, _write(tmp_path, "short.lfdoc", blob), blob)


def test_both_reject_a_header_that_runs_past_the_end(runner, tmp_path):
    """The length field is checked against the file, not trusted.

    This is what a half-downloaded container looks like, and treating it as a
    bad key would send someone hunting for a crypto problem.
    """
    blob = sealed_mod.CONTAINER_MAGIC + struct.pack(">I", 4096) + b'{"doc_id":"D"}'
    _rejects_both(runner, _write(tmp_path, "truncated.lfdoc", blob), blob)


def test_both_reject_an_absurd_header_length(runner, tmp_path):
    """A declared header larger than ``_MAX_HEADER``, which must be refused
    before anything tries to allocate it."""
    blob = (sealed_mod.CONTAINER_MAGIC + struct.pack(">I", (1 << 20) + 1)
            + b"x" * 32)
    _rejects_both(runner, _write(tmp_path, "big.lfdoc", blob), blob)


def test_both_reject_a_header_that_is_not_json(runner, tmp_path):
    blob = sealed_mod.CONTAINER_MAGIC + struct.pack(">I", 5) + b"nope!" + b"ct"
    _rejects_both(runner, _write(tmp_path, "notjson.lfdoc", blob), blob)


def test_both_reject_a_header_that_is_not_utf8(runner, tmp_path):
    """``TextDecoder`` is constructed with ``fatal: true`` for exactly this.

    Without it, invalid bytes become U+FFFD and the failure surfaces later as a
    JSON error or, worse, as a header with silently mangled text.
    """
    blob = (sealed_mod.CONTAINER_MAGIC + struct.pack(">I", 4)
            + b"\xff\xfe\xfd\xfc" + b"ct")
    _rejects_both(runner, _write(tmp_path, "badutf8.lfdoc", blob), blob)


@pytest.mark.parametrize("payload", [b"[]", b'"a string"', b"42", b"null"])
def test_both_reject_a_header_that_is_not_an_object(runner, tmp_path, payload):
    """Valid JSON, wrong shape. Every one of these parses, so without the shape
    check the caller would get a string where a dict belongs and crash later
    with an unrelated message."""
    blob = (sealed_mod.CONTAINER_MAGIC + struct.pack(">I", len(payload))
            + payload + b"ct")
    _rejects_both(runner, _write(tmp_path, f"shape{len(payload)}.lfdoc", blob),
                  blob)


def _package():
    kem_pub, _ = pqc.kem_keypair(pqc.KEM)
    return ca_mod.encrypt_framed_payload(
        "text", b"%PDF-1.4\n", "DOC-0000", "internal", kem_pub,
        extra_manifest={"created": "2026-01-01T00:00:00+00:00",
                        "font": "DejaVuSans", "pages": 1})
