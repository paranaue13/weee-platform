# WEEE Platform Build 2.5.1 — intermediate

Warehouse AΗΗΕ UI update:
- 2-row / 4-column KPI header.
- Current month receipts, total classifications, classified to process/ship, processing month, WEEE shipments month, current stock process/ship.
- Major categories 1–6 visually merged by rowspan.
- Short dash for unavailable values.
- Negative values highlighted red with a red dot on the corresponding column header.
- Sticky table headers on long desktop lists, applied globally.
- Preserves the July 2026 imported database in `backend/weee_dev.db`.

Note: `Αποστολές ΑΗΗΕ μήνα` remains 0 until the dedicated raw-WEEE dispatch workflow is implemented; it is deliberately not mixed with finished-material loadings.
