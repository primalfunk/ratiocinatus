# Testing and baseline maintenance

Run `python -m pytest -q` from a clean checkout. The suite is offline and needs
no model weights, GPU, external executable, commercial service, or user file.
It covers strict construction and schemas, canonical round trips and hashing,
identifiers, clocks, configuration precedence and redaction, workspace
versions, source duplicates and mutation, provider discovery/failure/malformed
behavior, operation failure records, append-only provenance, artifact and
lineage integrity, replay match/mismatch/unsupported states, export, reports,
structured CLI output, and exit codes.

Generate schemas with:

```console
python -m ratiocinatus.cli schema-export schemas
```

Regenerate proof baselines only from a clean deterministic workspace and record
the exact commands and hashes in `reports/phase-0-completion.md`. Never update a
baseline merely to make an unexplained test failure pass.

