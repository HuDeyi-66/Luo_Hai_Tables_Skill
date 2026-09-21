"""The standalone LuoHai entry point.

One function, no framework. It takes the workbook you have -- a path, raw bytes,
or an artifact you built yourself -- and returns tabular evidence with located
cells and ranges, explicit loss, and native citations.

LuoHai is an independent open-source component. This module is the whole of its
required surface: nothing here needs a runtime, a service, a registry or a
network, and nothing here imports a private implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .backends import FixtureXlsxBackend, TabularBackend
from .contracts import TableArtifact, TableEvidenceSkill, TableRunResult

__all__ = ["run_tabular_evidence", "evidence_skill", "workbook_artifact"]


def evidence_skill(reader: TabularBackend | None = None) -> TableEvidenceSkill:
    """Construct the LuoHai Skill, with the deterministic reader by default."""
    from .xlsx_extraction import TabularEvidenceSkill

    return TabularEvidenceSkill(reader or FixtureXlsxBackend())


def workbook_artifact(
    source: str | Path | bytes | TableArtifact,
    *,
    artifact_id: str | None = None,
    media_type: str | None = None,
) -> TableArtifact:
    """Coerce ``source`` into a re-verifiable workbook artifact.

    A path is read and digested; bytes are digested as given; an artifact you
    built yourself is passed through untouched, because re-deriving its identity
    would discard the record you made.
    """
    if isinstance(source, TableArtifact):
        return source
    if isinstance(source, (bytes, bytearray)):
        from .contracts import table_digest_bytes

        payload = bytes(source)
        return TableArtifact(
            artifact_id=artifact_id or "memory",
            digest=table_digest_bytes(payload),
            media_type=media_type
            or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            byte_length=len(payload),
        )
    path = Path(source)
    return TableArtifact.from_file(
        path,
        artifact_id or path.stem or "workbook",
        media_type=media_type,
    )


def run_tabular_evidence(
    source: str | Path | bytes | TableArtifact,
    *,
    artifact_id: str | None = None,
    media_type: str | None = None,
    source_id: str | None = None,
    options: Mapping[str, Any] | None = None,
    reader: TabularBackend | None = None,
) -> TableRunResult:
    """Extract tabular evidence from ``source``.

    Parameters
    ----------
    source:
        A filesystem path, the raw bytes, or a :class:`TableArtifact` you built
        yourself.
    artifact_id:
        Local handle for the artifact. Defaults to the file stem, or ``"memory"``
        for raw bytes. Ignored when ``source`` is already an artifact.
    media_type:
        Declared media type. Defaults to the extension-based guess.
    source_id:
        Identity the emitted units carry. Defaults to the artifact id: units must
        reference a source, and this Skill will not invent one.
    options:
        Skill options. See ``DEFAULT_OPTIONS``.
    reader:
        Alternative reader implementing the Skill's ``TabularBackend`` contract.

    Returns
    -------
    TableRunResult
        Units, run diagnostics and the capability statement. A workbook the Skill
        cannot read still returns a result -- with the loss or the refusal
        recorded -- rather than raising.

    Examples
    --------
    ::

        from skills.luohai import run_tabular_evidence

        result = run_tabular_evidence("throughput.xlsx", source_id="ports")
        for unit in result.units:
            print(unit.address.value, unit.loss)
        print(result.is_complete_success)
    """
    artifact = workbook_artifact(source, artifact_id=artifact_id, media_type=media_type)
    skill = evidence_skill(reader)
    return skill.run(
        artifact,
        source_id=source_id or artifact.artifact_id,
        options=options,
    )
