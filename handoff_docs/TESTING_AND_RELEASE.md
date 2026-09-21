# WEEE Platform — testing and release protocol

The user explicitly requires runtime/API/regression checks before every update. Compilation alone is not sufficient.

## Required checks before returning a build
1. Python compile / compileall.
2. JavaScript syntax check (Node where applicable).
3. Runtime-style JS test/harness if a real browser cannot be used.
4. FastAPI integration test with TestClient against a copy/temp database:
   - startup/login
   - main endpoints touched by the change
   - ensure migrations/backfills run safely
5. Targeted regression tests for every changed feature.
6. Verify bundled/real historical counts and mandatory known totals.
7. Review any failing old tests before treating them as authoritative; several historical tests may be version-locked/stale.

## Mandatory historical checks
Receipts/sorting expected values:
- 1,077 trips
- 1,077 sorting sessions
- max receipt date 2026-08-31
- August trips 65

Production mandatory August values:
- total 130,442 kg
- HERMES 7,134 kg
- OTHER 123,308 kg

Warehouse:
- no unexplained negative current stock by WEEE code
- verify arithmetic by code/month
- do not solve missing prior inventory by silently clipping values at zero

Production UI/aggregation:
- expand/collapse of header hierarchy must not change total kg
- `Σύνολο περιόδου` cannot overlap a date row

Registries:
- open Registries → immediately click a non-first subtab → selection must remain there; it must not reset to the first tab

Materials:
- active iff ERP code is present
- precious material export increment 0.05 kg
- all other materials export increment 0.5 kg

## Browser E2E limitation
In the previous development container, browser navigation to local `localhost`/`file://` was blocked by administrator/environment policy. If the new environment allows browser E2E, use it. If not, state the limitation and substitute a meaningful mocked/runtime JS harness rather than claiming visual E2E was performed.

## Release packaging
- development build filename must contain `intermediate`
- keep consistent incremental versioning
- root folder name should match ZIP name
- do not include `.venv`
- preserve persistent LocalAppData database semantics
