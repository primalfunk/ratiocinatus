# Dependency inventory

Phase 0 has one runtime dependency: Pydantic `>=2.8,<3` for strict runtime
contracts and derived schemas. setuptools `>=68` is the build backend. Pytest
`>=8` and coverage.py `>=7` are development-only. Python 3.11 or newer is the
platform prerequisite.

There are no required external executables, production providers, model
weights, GPUs, networks, or commercial services. Six provider families are
represented by internal deterministic mocks only. Resolve the environment's
transitive inventory with `python -m pip freeze`; it is not authoritative
project state because installed environments vary.


