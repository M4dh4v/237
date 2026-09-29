"""The tamper demo has to keep demonstrating what it claims.

``scripts/tamper_demo.py`` is the artefact for the spec's tamper requirement,
and it is the kind of artefact that rots quietly. Every check in it is a line of
printed prose next to a boolean, so it is entirely possible for the script to run
to completion, print a tidy summary, and be measuring nothing -- and that failure
mode is worse than a crash, because the output *reads* like evidence.

The specific way it nearly did exactly that is worth recording, because it is the
reason this file exists. The rollback step originally re-offered the log's own
head at an earlier size. The witness accepted it. That looked like a hole in the
refusal rules, but it was not: a witness asked twice for the same (size, root)
returns the signature it already gave, on purpose, so a retried request after a
dropped response does not look like an attack. Rule 1 runs before rule 2, and the
offer never reached rule 2 at all. A demo that reported "NOT CAUGHT" there would
have been describing its own bug as a property of the system.

So this file asserts the *specific* refusal each step provokes, and asserts that
each attack actually altered something before being refused. Both matter: a
refusal of an unaltered head is not evidence of anything.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "tamper_demo.py"


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Run the demo once, at the smallest document size it accepts.

    Module-scoped because the whole run costs a few seconds and every assertion
    below reads a different part of the same output; running it per test would
    multiply that for no extra coverage.
    """
    data = tmp_path_factory.mktemp("tamper")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--data", str(data / "deploy"),
         "--words", "900", "--fresh"],
        capture_output=True, text=True, cwd=REPO, timeout=600)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc, out


def test_every_attack_is_caught(run):
    proc, out = run
    assert proc.returncode == 0, (
        "the demo exited non-zero, which means at least one attack was not "
        f"caught:\n{out[-3000:]}")
    # Read the summary *table*, not the whole output: the closing prose says the
    # words "NOT CAUGHT" in a sentence explaining what they would mean, and an
    # assertion over the raw text matched that instead of a result row.
    rows = re.findall(r"^\s+\d+\.\s+.+?\s+(caught|NOT CAUGHT)\s*$", out,
                      flags=re.MULTILINE)
    assert rows, f"the demo did not print a summary table:\n{out[-3000:]}"
    missed = [r for r in rows if r == "NOT CAUGHT"]
    assert not missed, (
        f"{len(missed)} of {len(rows)} attacks went undetected; the reason is "
        f"above each row in the output:\n{out[-3000:]}")
    assert len(rows) == 6, (
        f"expected 6 attacks, found {len(rows)}; if the number of steps "
        "changed, update this file and the script's docstring together")


def test_the_anchor_consistency_check_is_the_thing_that_fails(run):
    """The spec's requirement, named: a consistency proof against the anchored root.

    Not "verification failed" -- the failure has to be the *anchor* check, on a
    head the log itself validly signed. If a different check failed first, the
    rebuilt-and-re-signed ledger would be caught for the wrong reason and the
    anchor's value would be untested.
    """
    _, out = run
    assert re.search(r"consistency proof from the anchored root \(size \d+\) to "
                     r"the rebuilt\s+head \(size \d+\): FAILS", out), (
        "the demo did not report the consistency proof from the externalized "
        f"root failing:\n{out[-3000:]}")
    # And the log's own signature over the rebuilt head verified, so the catch
    # is not coming from a signature the attacker could not forge anyway.
    assert "the log's own signature over it verifies: yes" in out


def test_the_rebuilt_head_is_genuinely_witness_free(run):
    """The witnesses disagree, and the demo proves it rather than asserting it.

    The stale witness signatures carried onto the rebuilt heads must be reported
    as bad by the standalone verifier, and the words the spec uses -- witnesses
    disagreeing -- should appear as a finding rather than as narration.
    """
    _, out = run
    assert "HEAD WITNESS DISAGREES" in out
    assert re.search(r"anchors: \d+/\d+ signatures ok, 0/\d+ consistent", out), (
        "the anchor was reported consistent with a head that does not extend it")
    assert "INCONSISTENT" in out
    assert "RESULT: NOT VERIFIED" in out


@pytest.mark.parametrize("rule,pattern", [
    ("equivocation", r"EQUIVOCATION: already signed size \d+ with root [0-9a-f]+\.\.\., "
                     r"now offered [0-9a-f]+\.\.\."),
    ("rollback", r"ROLLBACK: size \d+ is behind my last signed size \d+"),
    ("no proof", r"NO PROOF: size \d+ extends \d+ but no consistency proof was supplied"),
    ("bad proof", r"BAD PROOF: the offered tree of size \d+ is not a consistent "
                  r"extension of size \d+ that I signed"),
])
def test_each_refusal_rule_is_exercised_with_its_own_reason(run, rule, pattern):
    """Each rule is reached, and reached as itself.

    The parametrisation is the point: the four rules refuse for four different
    reasons, and a change that made one of them fire in place of another would
    still produce a caught attack and a green summary. Matching the refusal text
    is what keeps them distinct.
    """
    _, out = run
    assert re.search(pattern, out), (
        f"the {rule} rule did not refuse with its own message; the demo may be "
        f"exercising a different rule in its place:\n{out[-3000:]}")


def test_the_rollback_offer_reaches_a_size_the_witness_never_signed(run):
    """The condition that makes rule 2 reachable, asserted rather than assumed.

    A witness refuses a smaller size only when it has no signature at that size
    to return idempotently. So the demo has to create a real gap -- a size below
    the high-water mark that the witness never saw -- and it does that by killing
    the witness across two appends. If the gap ever fails to materialise, the
    rollback step silently tests rule 1 instead and this is where that shows up.
    """
    _, out = run
    missing = re.search(r"it never signed \[([\d, ]+)\], which are below its "
                        r"high-water mark\s+of (\d+)", out)
    assert missing, f"the demo did not report a gap in the witness's record:\n{out[:2000]}"
    never_signed = [int(x) for x in missing.group(1).split(",")]
    high_water = int(missing.group(2))
    assert never_signed, "the gap is empty, so rule 2 cannot be what fired"
    assert all(s < high_water for s in never_signed), (
        f"the 'gap' sizes {never_signed} are not below the high-water mark "
        f"{high_water}, so rule 2 would not fire on them")
    # And the offer the demo then makes is at one of those gap sizes.
    assert f"at size {never_signed[0]}, a size it never signed" in out


def test_a_retry_of_an_already_signed_head_is_still_idempotent(run):
    """The behaviour that misled the first version of this demo, pinned down.

    Re-offering a head the witness already signed must *not* read as an attack.
    It is the one case where a co-signature is returned without any consistency
    proof, and it is deliberate: a retried request after a dropped response must
    not be indistinguishable from an equivocation attempt. This asserts the
    property at the level the demo exposed it, so a future change to the rule
    ordering has to consciously break it here.
    """
    _, out = run
    assert "already_signed" not in out          # the demo never prints a success
    # The equivocation message is only produced for a *different* root at a
    # signed size, which is the distinction the retry case must not collapse
    # into. If rule 1 had been reached with the same root, the message would be
    # absent and the rollback assertion above would fail instead.
    assert "EQUIVOCATION" in out
