# Workspace report

The Phase 0 workspace uses format 0.1.0 and canonical-json-1. Portable
canonical records are stored as JSON or append-only JSON Lines, never solely
inside a database. An exclusive writer lock constrains accidental simultaneous
mutation. Initialization, open, inspection, validation, and export passed in
the tested environment.

