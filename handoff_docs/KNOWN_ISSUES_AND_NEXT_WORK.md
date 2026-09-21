# WEEE Platform — known issues / next work

This file describes requirements that were still important at handoff time. Verify current 2.5.35 behavior before deciding whether an item is already fully solved.

## Highest priority
### 1. Warehouse correctness and presentation
The user previously saw negative WEEE processing stock and negative opening-stock rows. 2.5.35 contains a correction for historical sorting movement dates and explicit carry-in handling, but validate the result with real data and the accounting identity in `BUSINESS_RULES.md`.

The warehouse visual design in 2.5.34 did not match the agreed proposal. Bring it to the full-width compact KPI/table style in `UI_UX_SPEC.md`.

### 2. Registries visual redesign
The user explicitly rejected the 2.5.34 Registry look even though it was functionally table-based. The next work should use one coherent shared Registry workspace/component across all Registry tabs.

AHEE and Material rows should have clear compact list views with full profile popups, not an unreadably wide dump.

### 3. Materials data mapping completeness
The 2.5.34 screenshot showed many active ERP rows where HER/Reptool/EWC fields were blank even though the reference table contains mappings for many entries. Rebuild/validate the mapping from `materials_reference_source.md` deterministically.
Do not fill blanks by inference.

### 4. Production table header
The 2.5.34 Production header was too tall and repetitive.
Implement the agreed major → official → internal hierarchy, avoid redundant child totals/codes, make names more readable, add stronger separators between categories 1–6, and fix footer overlap.

### 5. Period picker and Settings picker interaction
If not fully implemented in 2.5.35, complete the approved picker designs described in `UI_UX_SPEC.md`.

### 6. Tab performance
The user perceives small delays when entering Receipts, Sorting, Warehouse and Production. 2.5.35 introduced cache/prefetch changes. Measure and verify that:
- shell appears immediately
- revisit is near-instant when data are valid in cache
- only relevant mutations invalidate cached data
- no double fetch occurs on tab entry

### 7. Registry first-click bug
The user reported: enter Registries → click another subtab (e.g. suppliers) → app returns to first registry tab once; after that it behaves. 2.5.35 includes a fix. Keep this as a permanent regression test.

## Additional pending/continuing requirements
- Containers must have a real carrier/transporter relationship editable in create/edit flows.
- Employees can belong to multiple departments; keep the compact multi-department selector.
- Departments can have multiple positions; internal codes stay backend-only where necessary.
- Add/keep Customers (`Πελάτες`) registry.
- Registry tab names are `ΑΗΗΕ` and `Υλικά`, not `ΑΗΗΕ διάκριση` or `Υλικά ERP`.
- `Προς επεξεργασία` should be registry-driven for WEEE production filtering.
- HERMES report separation must remain correct.
