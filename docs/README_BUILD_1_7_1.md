# WEEE Platform Build 1.8

- Unified Windows / Backend / Android version 1.8.
- Removes operational “Χύμα” pseudo-materials from company WEEE master data.
- Adds company internal child categories under official parents (official mapping preserved).
- Android visual grouping for Category 1 and 2.
- Submitted sorting remains hidden from operators; Logistics/Management can reopen it.
- Android and Windows lists auto-refresh while active.
- Preparation for dynamic Windows receiving by Container / Curtain / Small Points.

- Fix: submitted sorting loads are excluded from Android even if an InboundLoad status is stale; mobile fetches use no-store cache semantics.
