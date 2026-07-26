# Phase 0 architecture and operating guide

## Boundaries

Phase 0 implements evidence registration and infrastructure only. Every mock
output carries `synthetic: true`; no mock claims to inspect media, transcribe
speech, identify speakers, reason, adjudicate, score, or render production
output.

## Contracts and serialization

Strict immutable Pydantic runtime models in `contracts.py` reject unknown
fields and export their own JSON schemas. Canonical JSON version
`canonical-json-1` is UTF-8, lexicographically key-sorted, contains no
insignificant whitespace, preserves array order, emits enum values, represents
durations as integer microseconds and datetimes as timezone-aware RFC 3339
strings, includes explicit nulls, and rejects NaN/Infinity and unsupported
objects. Hashes are lowercase SHA-256 over these exact bytes.

## Identifiers

Identifiers contain a namespace (`ws`, `src`, `art`, `op`, `inv`, `prov`,
`finding`, or `report`) and the first 128 bits of a SHA-256 digest of
canonical normalized inputs. Source IDs are content-derived, artifact IDs are
type-and-content-derived, and operation/invocation/provenance/report IDs are
deterministic from normalized inputs. Workspace IDs include the effective
configuration and injected clock. No random identifiers are used in Phase 0.

## Workspace format

`manifest.json` and `configuration.json` are canonical. Sources, provenance,
operation requests/results, and provider invocations/results are append-only
JSON Lines. Artifact envelopes are immutable canonical JSON files addressed by
typed ID. Validation, replay, reports, and exports occupy separate directories.
An exclusive `.writer.lock` constrains simultaneous mutation. Opening an
unsupported workspace version fails safely. Canonical state never exists only
in an opaque database.

The original source is only read. Registration stores its reference,
MIME-type guess, byte length, and SHA-256. `--copy-sources` optionally creates
a byte-identical evidence copy addressed by digest. Same-content files receive
the same source ID and later registrations record `duplicate_of`; modified
content receives a different identity. Verification detects later mutation.

## Configuration

Precedence is defaults, configuration-file values (library API), environment,
then CLI. Supported environment keys are `RATIOCINATUS_LOG_LEVEL`,
`RATIOCINATUS_DETERMINISTIC`, `RATIOCINATUS_COPY_SOURCES`, and
`RATIOCINATUS_REPORT_OUTPUT`. Keys containing secret, password, token, api_key,
or apikey are redacted before snapshot construction and are not accepted as
authoritative contract fields. Every operation embeds its immutable effective
configuration. Deterministic workspaces use `2000-01-01T00:00:00Z`.

## Providers and replay

Six explicit provider capabilities exist: media inspection, transcription,
diarization, embedding generation, structured generation, and rendering.
Each has a deterministic visibly synthetic mock with success, typed failure,
malformed-output, and availability behavior. Registry selection is explicit,
and duplicate identities are refused.

Replay loads the original operation request and its preserved parameters,
selects the recorded deterministic provider, recreates the authoritative
artifact, and compares canonical payload hashes. Unsupported operation types
produce an explicit `unsupported` result; unequal hashes produce `mismatch`.

## Validation and logs

Workspace validation checks source bytes, artifact hashes, creation operations,
provenance references, and dependency references, returning severity-bearing
machine-readable findings. Reports are also available as human-readable text.
Structured logs are operational evidence and intentionally are not canonical
provenance.

## Limitations

Phase 0 has no production providers, media parsing, normalization, database
index, multi-user concurrency, remote sources, analytical ontology, GUI,
adjudication, scoring, or audiovisual output. Source paths are local references;
portable proof exports require `--copy-sources`. Replay supports deterministic
provider operations only. These are deliberate Phase 0 boundaries, not claims
of completed later capabilities.

