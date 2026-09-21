# WEEE Platform 2.5.22 Intermediate

## Real 2026 data
- Replaces the old receipt/sorting test history with 1,077 real receipt records from Jan–Aug 2026.
- A/A Παραλαβής uses the source Αριθμός Εντολής.
- Imports DPP, dispatch note, seal, weighbridge, vehicle, actual container where present, non-WEEE/foreign material data, special-waste data and load flags.
- Source workbooks do not provide reliable arrival time; imported historical records display time as unavailable rather than inventing one.
- Imports 8,279 WEEE classification entries; their weight total exactly matches receipt net WEEE weight: 1,796,363 kg.
- Load type business rules for Soultanoglou/Samaras/Perkas/Cosmote are applied during import.

## Data migration / persistence
- A one-time migration removes old operational receipt/sorting/derived WEEE-stock test data but preserves Master Data, users, roles and registry edits.
- Existing Windows installations continue using `%LOCALAPPDATA%\\WEEE Platform\\data\\weee_dev.db`; future intermediate builds reuse that persistent DB.
- Fresh installs ship with the same imported 2026 dataset already seeded.

## UI
- Receipts: current day first, global search, date+time context in search results, clickable monthly aggregate view, compact two-line metrics, responsive scrolling.
- Sorting: Receipts-style Days/Months layout, calendar, search/filter controls, clickable rows opening the sorting sheet.
- WEEE Warehouse: current day first, Days/Months history, full-width scrolling tables, sticky headers, parent-code display for internal subcategories, previous-period stock carried from the prior calendar close.
- Sidebar: consistent line-icon language, Light/Dark/System appearance menu, real signed-in username/role display and role-level overview.
- Calendar today marker is visually distinct from the selected date.

## Validation performed
- Python compilation: OK.
- JavaScript syntax (`node --check`): OK.
- API/data validation: 1,077 receipts, 1,077 sorting sessions, 8,279 sorting entries, 1,796,363 kg receipts = 1,796,363 kg classification.
- August closing WEEE stock = September opening WEEE stock: 1,796,363 kg (no production/outgoing data yet).
- Registry preservation migration test: OK.
- Relevant regression tests for Receipts / Sorting / Registries: 7 passed.
- Browser automation was attempted in the build container, but localhost browser navigation is blocked by the environment administrator; therefore final Windows visual/runtime verification remains a user-side smoke test.
