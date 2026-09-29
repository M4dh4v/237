"""Making child processes die when the process that started them dies.

Every long-running child in this tree is a server: the witness nodes
(``logfirst.witness.node``) and the authority (``logfirst.authority.server``).
They are started by a parent that is expected to outlive them -- a demo script,
or a test session -- and the parent normally shuts them down on the way out.

The word doing the work there is *normally*. A parent that exits cleanly runs
its ``finally`` blocks and terminates its children. A parent that is killed
outright -- ``kill -9``, a CI runner reaping a job, an editor stopping a test
session -- runs nothing at all, and the children are reparented to init and keep
running. They keep their listening sockets, too.

That is not a cosmetic leak, because of what these particular children are:

* A surviving **witness** holds its port and answers ``/cosign`` from its own
  state file. The next run to want that port either fails to bind, or -- far
  worse -- binds nothing and talks to the survivor, which refuses the new
  deployment's heads as rollbacks. The symptom is a witness quorum that will not
  form, which reads as *tamper detection working*. It is a dirty port.
* A surviving **authority** keeps a ledger open and will keep appending to it.

``WitnessFleet._check_ports_free`` catches the first case and refuses to start
with a message that names it, which is why the failure is legible rather than
mysterious. But refusing to start is a workaround for a leak, not a fix for one,
and it cannot help the other direction: a *live* demo whose witnesses were
started by a process that has since been killed.

What this module adds is the kernel-level guarantee instead of a convention:
``PR_SET_PDEATHSIG`` asks Linux to send the child a signal when its parent
*thread* dies, however the parent dies. A SIGKILLed test session is then no
different from a clean one, as far as the children are concerned.

Two caveats, both handled rather than assumed:

* It is Linux-specific. Elsewhere this returns ``None`` and children keep the
  old behaviour -- started and stopped by their parent, orphaned if it is
  killed. Said out loud rather than silently doing nothing.
* The signal fires when the parent *thread* exits, not the whole process. A
  child forked from a worker thread dies when that thread ends, which is early.
  Nothing here forks from a thread today; the note is here because the failure
  would look like a child dying for no reason.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from typing import Callable

__all__ = ["die_with_parent", "Popen"]

# ``CDLL(None)`` opens the namespace of the running program, which is how libc's
# symbols are reached without hardcoding "libc.so.6" -- that name is glibc's and
# does not exist under musl. Loaded once at import: everything in the child
# below runs between fork and exec, where allocating is what you want to avoid.
try:
    _libc: ctypes.CDLL | None = ctypes.CDLL(None, use_errno=True)
except OSError:                                     # pragma: no cover
    _libc = None

_PR_SET_PDEATHSIG = 1


def die_with_parent(sig: int = signal.SIGTERM) -> Callable[[], None] | None:
    """A ``preexec_fn`` that makes the child die with this process, or ``None``.

    ``None`` on any platform without ``PR_SET_PDEATHSIG``, which is the honest
    answer: :class:`subprocess.Popen` treats ``preexec_fn=None`` as "no hook",
    so callers pass the result straight through and get the portable behaviour
    everywhere else without a branch of their own.
    """
    if _libc is None or not sys.platform.startswith("linux"):
        return None

    parent = os.getpid()

    def _preexec() -> None:                         # pragma: no cover - in child
        # Between fork and exec, so: no logging, no formatting, no allocations
        # beyond the call itself, and never an exception -- there is nowhere for
        # one to go but a child that hangs half-created.
        _libc.prctl(_PR_SET_PDEATHSIG, sig, 0, 0, 0)
        # The race this closes: if the parent died between ``fork`` and the call
        # above, the kernel delivered the signal to nobody and never will, and
        # this child is already an orphan. Its parent is now init (1). Exit
        # rather than become exactly the process this module exists to prevent.
        if os.getppid() != parent:
            os._exit(1)

    return _preexec


def Popen(*args, **kwargs) -> subprocess.Popen:
    """``subprocess.Popen`` that sets ``die_with_parent`` unless told otherwise.

    A drop-in for the call sites that spawn servers, so "does this child outlive
    a kill -9 of its parent?" is answered once, here, rather than at each one.
    An explicit ``preexec_fn`` in ``kwargs`` wins: a caller with a reason to
    want something else should not have to work around this.
    """
    if "preexec_fn" not in kwargs:
        kwargs["preexec_fn"] = die_with_parent()
    return subprocess.Popen(*args, **kwargs)
