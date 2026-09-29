"""Servers must not outlive the process that started them.

Why this file exists: killing a test session with ``SIGKILL`` left the witness
and authority subprocesses running. Nothing runs a ``finally`` block when the
parent is killed outright, so the children were reparented to init and kept
their listening sockets -- and a surviving witness answers ``/cosign`` from its
*own* state file, refusing the next deployment's heads as rollbacks. The symptom
is a witness quorum that will not form, which reads like tamper detection
working. It is a dirty port.

The fix is ``PR_SET_PDEATHSIG`` (see ``logfirst/proc.py``). These tests are
written against the property rather than the mechanism, because the mechanism
working and the property holding are different claims and only the second one
matters:

* the first spawns a real child of a real intermediate process, kills the
  intermediate process with ``SIGKILL``, and requires the child to be gone;
* the next two do it with the actual :class:`WitnessFleet` and the actual
  authority server, and then check the *ports* are free -- which is what a
  later run actually trips over.

The intermediate process is a real one, not the test process: pytest is not
what gets killed in the situation this file is about, so a child of the test
process would prove nothing.

The last two cases pin the platform behaviour rather than hiding it. Where the
kernel cannot do this, ``die_with_parent`` returns ``None``, children are
orphaned, and the test says so instead of asserting a guarantee that does not
hold there.
"""

from __future__ import annotations

import json
import os
import select
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from logfirst import proc

REPO = Path(__file__).resolve().parent.parent

LINUX = sys.platform.startswith("linux")
requires_pdeathsig = pytest.mark.skipif(
    not LINUX, reason="PR_SET_PDEATHSIG is Linux-specific")


def _free_ports(n: int) -> list[int]:
    out = []
    for _ in range(n):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            out.append(s.getsockname()[1])
    return out


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:                     # pragma: no cover
        return True
    return True


def _wait_gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _port_answers(port: int) -> bool:
    """True if something is listening. Used after the parent is gone, so the
    check must not be satisfied by the parent's own socket."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _wait_port_free(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _port_answers(port):
            return True
        time.sleep(0.1)
    return False


# The intermediate process's body is written to a file rather than passed as
# ``-c``: it is three or four statements of real setup, and string-concatenated
# code is where a test stops being readable enough to trust.
MIDDLE_HEADER = '''
import json, os, subprocess, sys, time
sys.path.insert(0, {repo!r})
from logfirst import proc
from logfirst.data.deploy import Deployment, WitnessFleet
cfg = json.loads(os.environ["MIDDLE_CFG"])
pids = []


def report():
    print(json.dumps(pids), flush=True)


'''


def _start_middle(tmp_path: Path, body: str, cfg: dict) -> subprocess.Popen:
    """Start a real intermediate process that will itself start a child."""
    script = tmp_path / "middle.py"
    script.write_text(MIDDLE_HEADER.format(repo=str(REPO)) + body,
                      encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, str(script)], cwd=str(REPO),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONPATH": str(REPO),
             "MIDDLE_CFG": json.dumps(cfg)})


def _drain(stream, timeout: float = 5.0) -> str:
    """Read whatever has arrived on a pipe, and give up rather than wait for EOF.

    ``read()`` and ``readline()`` on a pipe block until the write end closes,
    which a process that is merely *alive and quiet* never does. Every failure
    message in this file used to end in ``middle.stderr.read()``, so the moment
    a test wanted to explain itself it stopped being able to -- which is how
    this file came to hang for 400 seconds and report nothing.
    """
    deadline = time.time() + timeout
    out = []
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        ready, _, _ = select.select([stream], [], [], remaining)
        if not ready:
            break
        chunk = stream.readline()
        if not chunk:
            break
        out.append(chunk)
    return "".join(out)


def _read_pids(middle: subprocess.Popen, timeout: float = 60.0) -> list[int]:
    """The pid list the middle process was asked to report.

    Lines that are not the JSON array are skipped, not treated as the answer.
    Importing liboqs prints ``liboqs-python faulthandler is disabled`` on
    *stdout* before any code of ours runs, so the first line of a perfectly
    healthy middle process is a banner. Reading exactly one line and parsing it
    made this test fail on an unrelated warning from a dependency.
    """
    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            _fail(middle, f"reported no pid list within {timeout:.0f}s")
        ready, _, _ = select.select([middle.stdout], [], [], remaining)
        if not ready:
            continue
        line = middle.stdout.readline()
        if not line:
            _fail(middle, "stdout closed before a pid list arrived")
        try:
            pids = json.loads(line)
        except ValueError:
            continue
        if isinstance(pids, list) and pids:
            return [int(p) for p in pids]
        _fail(middle, f"reported {line.strip()!r}, not a non-empty pid list")


def _fail(middle: subprocess.Popen, why: str) -> None:
    """Explain a broken middle process, without blocking on it to do so.

    The kill comes first. ``stderr.read()`` waits for EOF, and a middle process
    that is alive and stuck never sends one, so reading before killing means the
    diagnostic itself is what hangs.
    """
    _kill_hard(middle)
    pytest.fail(f"{why}; stderr: {_drain(middle.stderr)[-2000:]}")


def _kill_hard(p: subprocess.Popen) -> None:
    """SIGKILL, then reap. This is the whole point: no ``finally`` runs."""
    p.kill()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:           # pragma: no cover
        pass


# ==========================================================================
# The property
# ==========================================================================

@requires_pdeathsig
def test_a_child_does_not_outlive_a_killed_parent(tmp_path):
    """The mechanism, on a process with nothing else to complicate it."""
    middle = _start_middle(tmp_path, '''
# DEVNULL, not inherited: a child holding the middle's stdout and stderr pipes
# keeps them open after the middle dies, so anything reading those pipes -- the
# failure diagnostic in this file included -- waits for a writer that no longer
# exists.
p = proc.Popen([sys.executable, "-c", "import time; time.sleep(300)"],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
pids.append(p.pid)
report()
time.sleep(300)
''', {})
    try:
        child = _read_pids(middle)[0]
        assert _alive(child)
        _kill_hard(middle)
        assert _wait_gone(child), (
            f"child {child} survived SIGKILL of its parent; it would have been "
            "reparented to init and kept its listening socket")
    finally:
        _kill_hard(middle)


@requires_pdeathsig
def test_a_killed_session_leaves_no_witness_holding_its_port(tmp_path):
    """The real case, and the one that actually bit: a witness fleet whose
    starter is killed must not keep answering on its ports.

    Asserted on the ports rather than only on the pids, because the port is what
    the next run collides with -- and a process that is gone but whose socket
    somehow lingered would still be the bug.
    """
    ports = _free_ports(3)
    middle = _start_middle(tmp_path, '''
dep = Deployment.create(cfg["data"], witness_ports=cfg["ports"], min_witnesses=2)
fleet = WitnessFleet(dep)
fleet.start()
pids.extend(p.pid for p in fleet.procs.values())
report()
time.sleep(300)
''', {"data": str(tmp_path / "data"), "ports": ports})
    pids: list[int] = []
    try:
        pids = _read_pids(middle)
        assert len(pids) == 3, f"expected three witnesses, got {pids}"
        assert all(_port_answers(p) for p in ports), "the witnesses never came up"

        _kill_hard(middle)

        for port in ports:
            assert _wait_port_free(port), (
                f"witness port {port} is still answering after the process "
                "that started the fleet was killed; the next run to want this "
                "port will talk to a stranger holding a stale state file")
        for pid in pids:
            assert _wait_gone(pid), f"witness {pid} survived its starter"
    finally:
        _kill_hard(middle)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


@requires_pdeathsig
def test_a_killed_session_leaves_no_authority_holding_its_port(tmp_path):
    """The other leaked child. An authority is worse than a witness here: it
    holds a ledger open and will keep appending to it."""
    auth_port = _free_ports(1)[0]
    ports = _free_ports(3)
    middle = _start_middle(tmp_path, '''
dep = Deployment.create(cfg["data"], witness_ports=cfg["ports"], min_witnesses=2)
for r in ("alice", "bob"):
    dep.add_recipient(r)
fleet = WitnessFleet(dep)
fleet.start()
env = {**os.environ, "PYTHONPATH": cfg["repo"]}
p = proc.Popen([sys.executable, "-m", "logfirst.authority.server",
                "--data", dep.data_dir, "--port", str(cfg["auth_port"]),
                "--no-tls",
                "--witness-ports", ",".join(str(x) for x in cfg["ports"]),
                "--min-witnesses", "2"],
               cwd=cfg["repo"], env=env,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
pids.append(p.pid)
report()
time.sleep(300)
''', {"data": str(tmp_path / "data"), "ports": ports,
      "auth_port": auth_port, "repo": str(REPO)})
    pid = None
    try:
        pid = _read_pids(middle)[0]
        deadline = time.time() + 30
        while time.time() < deadline and not _port_answers(auth_port):
            time.sleep(0.2)
        assert _port_answers(auth_port), "the authority never came up"

        _kill_hard(middle)

        assert _wait_port_free(auth_port), (
            f"the authority on port {auth_port} is still serving after its "
            "starter was killed")
        assert _wait_gone(pid), f"authority {pid} survived its starter"
    finally:
        _kill_hard(middle)
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


# ==========================================================================
# The wiring, and the places it does not apply
# ==========================================================================

def test_an_explicit_preexec_fn_is_not_overridden(tmp_path):
    """A caller with its own hook keeps it. ``proc.Popen`` fills in a default,
    and a default that silently replaced an explicit argument would be a worse
    bug than the one this module exists to fix.

    Observed through a file rather than a list, because ``preexec_fn`` runs in
    the forked child: an append to a parent object would happen in the child's
    copy of that object and the parent would never see it, so the assertion
    would fail even when the hook ran.
    """
    marker = str(tmp_path / "hook-ran")
    flag = os.O_CREAT | os.O_WRONLY

    def mine():
        os.close(os.open(marker, flag, 0o600))

    p = proc.Popen([sys.executable, "-c", "pass"], preexec_fn=mine)
    p.wait(timeout=30)
    assert os.path.exists(marker), (
        "proc.Popen replaced the caller's preexec_fn; the caller's hook never "
        "ran in the child")


def test_popen_is_a_drop_in(monkeypatch):
    """It passes everything else through untouched. Asserted by capturing the
    call rather than by spawning, because the point is the argument plumbing,
    not the process."""
    seen = {}

    def fake(*args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return "sentinel"

    monkeypatch.setattr(proc.subprocess, "Popen", fake)
    assert proc.Popen(["echo"], cwd="/tmp", text=True) == "sentinel"
    assert seen["args"] == (["echo"],)
    assert seen["kwargs"]["cwd"] == "/tmp"
    assert seen["kwargs"]["text"] is True
    assert callable(seen["kwargs"]["preexec_fn"])


def test_where_the_kernel_cannot_do_it_the_answer_is_none(monkeypatch):
    """The honest platform answer, asserted rather than assumed.

    ``preexec_fn=None`` means "no hook" to :mod:`subprocess`, so callers pass
    this straight through and get the portable behaviour -- children stopped by
    their parent, and orphaned if the parent is killed. That is a real
    limitation of every platform without ``PR_SET_PDEATHSIG``, stated here so
    nobody reads the tests above as a cross-platform guarantee.
    """
    monkeypatch.setattr(proc.sys, "platform", "darwin")
    assert proc.die_with_parent() is None


def test_the_hook_does_not_fire_on_a_live_parent():
    """A child that sets the hook while its parent is alive must survive to
    run. The failure this guards is the parent-death check deciding that a
    perfectly healthy parent is a dead one, which would kill every server the
    moment it started."""
    if not LINUX:
        pytest.skip("PR_SET_PDEATHSIG is Linux-specific")
    hook = proc.die_with_parent()
    assert hook is not None
    child = subprocess.Popen(
        [sys.executable, "-c", "print('survived')"],
        cwd=str(REPO), stdout=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONPATH": str(REPO)}, preexec_fn=hook)
    out, _ = child.communicate(timeout=60)
    assert child.returncode == 0, (
        f"a child that set the hook under a live parent exited "
        f"{child.returncode}; the parent-death check is firing too eagerly")
    assert out.strip() == "survived"
