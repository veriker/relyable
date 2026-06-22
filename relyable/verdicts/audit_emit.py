"""audit_emit — emit a re-derivable veriker audit bundle from a gate verdict.

This is the **attestation** layer. The enforcement core re-derives the verdict
*inside* the gate; this makes that verdict travel as a checkable claim: a veriker
audit bundle whose verifier RE-PARSES the committed JUnit report and rejects any
claimed verdict that does not match.

HONEST SCOPE — say exactly what the bundle proves and does not:
  * PROVES: the claimed verdict ``{tests_run, passed, failed, errored, skipped}``
    was correctly derived from THIS committed ``evidence/report.xml``, and that
    report is integrity-pinned (a re-stamped tamper still rides RED because the
    verdict is re-derived, not read).
  * DOES NOT PROVE: that re-running the suite reproduces this verdict. Test runs
    are not reproducible without sealed dependencies; reproducing the *run* is
    out of scope. The bundle attests derivation-from-a-pinned-report, not
    re-execution.

Axis-2 spec-pinned dispatch (mirrors examples/agent_honesty_minimal): the output
type ``agent_test_verdict`` is bound by a SHA-pinned spec to the verifier-side
primitive ``honesty_test_verdict_reparse``, compared ``exact``. The primitive is
registered from THIS module (host-side, re-derive-don't-trust), never by editing
audit_bundle/ substrate.

Like the gate, this module re-derives through the ``veriker`` substrate (a
declared dependency). The verdict re-derivation itself (``verdict.py``) uses only
the standard library, so a verdict can be re-derived with no third-party trust.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import GateConfig
from .gate import GateResult
from .verdict import TestVerdict, parse_junit_xml

# The veriker substrate (a declared dependency) provides ``audit_bundle``.
from audit_bundle.emitter import BundleContent, write_bundle
from audit_bundle.plugins.file_integrity_many_small import FileIntegrityManySmall
from audit_bundle.rederivation.registry import register_primitive
from audit_bundle.rederivation.spec_binding import SpecAnchor
from audit_bundle.verifier import BundleVerifier

# ---------------------------------------------------------------------------
# Constants — the bundle shape
# ---------------------------------------------------------------------------

_SPEC_SRC = Path(__file__).resolve().parent / "audit_assets" / "honesty.spec.json"
_SPEC_BASENAME = "honesty.spec.json"

_VERDICT_OUTPUT_ID = "test_verdict"
_VERDICT_TYPE = "agent_test_verdict"
_PRIMITIVE_ID = "honesty_test_verdict_reparse"

_REPORT_REL = "evidence/report.xml"
_TYPED_CHECKS = ["file_integrity_many_small"]
_DEFAULT_BUNDLE_ID = "relyable-verdict"
_SCHEMA_VERSION = "vcp-v1.1-canary4"


# ---------------------------------------------------------------------------
# Claim shape
# ---------------------------------------------------------------------------


def verdict_claim_value(verdict: TestVerdict) -> dict:
    """The claimed verdict dict the bundle carries (and the primitive re-derives).
    ``tests_run`` is the gate's total; the rest mirror the verdict counts."""
    return {
        "tests_run": verdict.total,
        "passed": verdict.passed,
        "failed": verdict.failed,
        "errored": verdict.errored,
        "skipped": verdict.skipped,
    }


# ---------------------------------------------------------------------------
# Verifier-side re-derivation primitive (host-side; registered here)
# ---------------------------------------------------------------------------


class HonestyTestVerdictReparse:
    """Re-derive the verdict by RE-PARSING the committed evidence/report.xml with
    the package's own hardened JUnit parser. The claimed value is never admitted;
    only this recomputation is compared (``exact``)."""

    primitive_id: str = _PRIMITIVE_ID

    def recompute(self, inputs, pack_section: dict):
        from audit_bundle.plugin import RecomputedValue  # noqa: PLC0415

        bundle_dir: Path = inputs.bundle_dir
        report_bytes = (bundle_dir / _REPORT_REL).read_bytes()
        verdict = parse_junit_xml(report_bytes)
        value = verdict_claim_value(verdict)
        detail = (
            f"re-parsed {_REPORT_REL}: {value['tests_run']} test(s), "
            f"{value['passed']} passed, {value['failed']} failed, "
            f"{value['errored']} errored, {value['skipped']} skipped"
        )
        return RecomputedValue(value=value, detail=detail)


def register_primitives() -> None:
    """Register the verdict re-derivation primitive. Idempotent (re-registering
    the same class is a no-op in the substrate registry)."""
    register_primitive(HonestyTestVerdictReparse())


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------


def emit_bundle(
    out_dir: Path,
    *,
    report_xml: bytes,
    verdict: TestVerdict,
    created_at: str,
    bundle_id: str = _DEFAULT_BUNDLE_ID,
) -> Path:
    """Write a re-derivable audit bundle attesting ``verdict`` against the
    committed ``report_xml``. Returns the bundle directory.

    ``report_xml`` MUST be the JUnit bytes the verdict was derived from — the
    primitive re-parses exactly these bytes, so a verdict that disagrees with the
    report is rejected at emit-verify time.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    spec_bytes = _SPEC_SRC.read_bytes()
    claim = json.dumps(
        {"value": verdict_claim_value(verdict)}, indent=2, sort_keys=True
    ).encode("utf-8")

    outputs_list = [
        {
            "output_id": _VERDICT_OUTPUT_ID,
            "type": _VERDICT_TYPE,
            "conforms_to": f"spec/{_SPEC_BASENAME}",
        }
    ]

    content = BundleContent(
        bundle_id=bundle_id,
        created_at=created_at,
        schema_version=_SCHEMA_VERSION,
        files={
            _REPORT_REL: report_xml,
            f"outputs/{_VERDICT_OUTPUT_ID}.json": claim,
        },
        spec_files={_SPEC_BASENAME: spec_bytes},
        cross_refs={},
        payload={},
        typed_checks=_TYPED_CHECKS,
        extra_manifest_fields={
            "fragment_anchors": {},
            "outputs": outputs_list,
        },
    )
    write_bundle(out_dir, content)
    return out_dir


def emit_from_gate_result(
    out_dir: Path,
    *,
    workspace: Path,
    config: GateConfig,
    result: GateResult,
    created_at: str,
    bundle_id: str = _DEFAULT_BUNDLE_ID,
) -> Path:
    """Emit a bundle from a completed :class:`GateResult`. Reads the committed
    JUnit at ``workspace/config.report_path`` (the report the gate's own run
    produced) and the re-derived verdict on the result.

    Raises ``ValueError`` if the gate did not conclude with a verdict (no report
    to attest) — you cannot emit an attestation for a run that did not conclude.
    """
    verdict = result.run.verdict
    if verdict is None:
        raise ValueError(
            "cannot emit an audit bundle: the gate run did not conclude with a "
            f"verdict ({result.run.reason})"
        )
    report_file = (Path(workspace) / config.report_path).resolve()
    if not report_file.is_file():
        raise ValueError(
            f"cannot emit an audit bundle: no JUnit report at {report_file}"
        )
    return emit_bundle(
        out_dir,
        report_xml=report_file.read_bytes(),
        verdict=verdict,
        created_at=created_at,
        bundle_id=bundle_id,
    )


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def _spec_anchor() -> SpecAnchor:
    raw = _SPEC_SRC.read_bytes()
    spec_id = json.loads(raw)["spec_id"]
    return SpecAnchor(allowed={spec_id: hashlib.sha256(raw).hexdigest()})


def build_verifier() -> BundleVerifier:
    """Register the primitive and return a verifier pinned to the committed spec.
    The anchor authority comes from the package's own committed spec bytes, never
    from the bundle's spec/ copy (the veriker SpecAnchor posture)."""
    register_primitives()
    return BundleVerifier(
        plugins=[FileIntegrityManySmall()], spec_anchor=_spec_anchor()
    )


def verify_bundle(bundle_dir: Path):
    """Convenience: verify a bundle this module emitted. Returns the substrate's
    verify result (``.ok``, ``.failures``)."""
    return build_verifier().verify(Path(bundle_dir).resolve())
