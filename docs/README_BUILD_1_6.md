# WEEE Platform Build 1.6 — Sorting UX

Build 1.6 focuses on the real Android sorting workflow tested on site.

## Main changes
- Operators see descriptions without WEEE six-character codes.
- All WEEE opens first by general categories 1–6.
- Separate quick flows: Χύμα Πλυντήρια / Κουζίνες and Χύμα Ψυγεία.
- Bulk category mapping follows the agreed WEEE codes internally.
- Washer/cooker flow choices: Αποθήκευση, Φόρτωση, Προς παραγωγή.
- Fridge flow choices: Αποθήκευση, Φόρτωση.
- Loading choice shows open loading orders.
- Collection-medium registry types updated to Infocycle 1/2, large/small baskets, 1kg sack, 2kg/UN sack, pallet and bulk (legacy types retained for database compatibility).
- Two weighing modes: scale gross reading with automatic tare/current-content calculation, or known net material weight.
- Existing open media containing the same material are suggested first; media previously used by the same operator are prioritized.
- Sorting entries are newest-first and can be edited/deleted while the sorting session is still open; audit events are retained.

## Important
The bulk destination choice is stored with the sorting entry so the later stock/production/loading transaction can follow the selected route after the sorting approval/close workflow. Direct Galaxy/production material conversion still depends on the configured material mappings.

## Test
13 automated tests pass, including Build 1.6 gross-scale calculation, medium suggestion, edit and delete.
