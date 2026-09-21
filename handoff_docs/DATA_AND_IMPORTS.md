# WEEE Platform — data and imports

## 1. Authoritative Jan–Aug 2026 receipts/sorting source
File: `Παραλαβές 1-8 2026.zip`

Expected imported real dataset:
- 1,077 inbound trips
- 1,077 inbound loads
- 1,077 sorting sessions
- 8,279 sorting entries
- 507 organizations
- latest receipt date: 2026-08-31
- August trips: 65

Before the real historical import, previous receipt/sorting test data were intended to be removed/replaced.

Imported fields include order number, DPP, dispatch note, seal, weighbridge, vehicle, container, foreign/non-WEEE data, special waste/classification flags and detailed WEEE weights.

Historical comments must not display automatic text such as `Ιστορική εισαγωγή από ...`.

## 2. Production source
File: `Διεκπεραιωμένα - επεξεργασμένα 1-8 2026.zip`

For the current historical production import use **tabs 1–2 only**:
- tab 1 → categories 1, 2, 4
- tab 2 → categories 5, 6

Tabs 3–6 are not part of this production import unless the user later explicitly changes the rule.

Historical production is imported into production work entries and reduces WEEE stock.
The source distinguishes HERMES and OTHER.

Mandatory August regression result:
- total 130,442 kg
- HERMES 7,134 kg
- OTHER 123,308 kg

A previous wrong figure of 152,069 kg came from double-counting; never use it.

Historical production entries may use an inactive/hidden organizational unit such as `HIST_PROD` so they count operationally without polluting active department lists.

## 3. Materials mapping source
File: `materials_reference_source.md`

This is the user's supplied reference for the Material canonical profile and includes rows/columns for:
- Γένος
- general/official descriptions
- Reptool descriptions
- HER descriptions
- ERP descriptions
- ERP codes
- EWC/ΕΚΑ codes
- Reptool codes

The table is wide and irregular. Treat it as authoritative data, but do not guess mappings where cells are blank or alignment is ambiguous. Build deterministic import/mapping validation.

Key rule: only rows with a non-empty **ERP code** are operationally active.

## 4. Persistent data
Registry edits should survive intermediate build replacements via the persistent local DB under LocalAppData. Build scripts/migrations must not accidentally overwrite user-maintained registry data.

When schema changes are required, write migrations/backfills that preserve existing data.
