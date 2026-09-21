# WEEE Platform Build 2.5

- Replaced strict dropdown/datalist behavior in the Windows receipt flow with custom floating autocomplete fields.
- Added receipt form fields needed for the official recycling report form: supplier, order number, carrier, seal number, recycler, container, weighbridge number, report date, dispatch note, non-WEEE materials, special-management wastes and recycler comments.
- All weight displays in receipts, sorting, warehouse and reports are rounded/displayed as integer kg.
- Today is visually marked in month/day tabs; selected year/month/day are darker.
- Removed count text like "· 1" from date/month tabs while keeping status dots.
- Added day/month receipt statistics, Ctrl+click multi-day selection, and a receipt report panel with filters plus CSV/Excel and PDF-print export.
- Whole receipt row opens the editable receipt card; clicking status opens sorting detail.
- Added delete receipt action for receipts whose sorting has not started.

## Historical July 2026 dataset
- Integrated from the supplied official daily reporting workbooks for July 2026.
- 147 load/order records across 145 inbound trips, total net receipt weight 209,163 kg.
- 07/07/2026 intentionally has no receipts.
- DPP 902 is represented as one Small Points trip with 3 separate load/order records.
- Historical sorting lines are imported from the official WEEE category rows in each daily workbook and marked closed for historical reporting.
- Missing source fields were not invented.
