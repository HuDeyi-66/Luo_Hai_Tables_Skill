# Public input contract hardening

`run_tabular_evidence` accepts paths, immutable OOXML workbook bytes, bytearrays (copied to immutable bytes), or a `TableArtifact`. Byte input uses the same OOXML reader and checks the artifact digest before extraction. There is no temporary file, formula evaluation or inferred authority. `TableArtifact.payload_bytes` is Skill-local input storage; serialized artifact metadata does not duplicate the payload. Metadata-only round trips require the original bytes before extraction.

Unreadable paths, including missing or permission-denied files, return a `TableRunResult` with fatal `artifact_input_unreadable`, zero units and `artifact = null`. No digest is fabricated for unread bytes. `is_complete_success` is false and the result is JSON-serializable. Lower-level `TableArtifact.from_file` and `workbook_artifact` retain their construction errors. Supplied artifacts preserve the caller's identity and fail closed on digest mismatch.

The default reader supports in-memory input. Injected readers without `load_bytes` report an attributable failure; existing path-only readers remain compatible. Existing explicit fallback settings are still honored and recorded. The Skill version is `0.1.1-provisional`; the shared SeaFlow Core is unchanged.
