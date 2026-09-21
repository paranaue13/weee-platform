# Build 2.5.6 Intermediate — verification

Implemented and checked in source:
- wider unified pastel workspace; day/month tabs wrap instead of forcing horizontal scrolling
- receipt statistics responsive layout
- subtle hover shadow on clickable controls/rows/items
- New Receipt opens as centered draggable non-modal panel
- Sorting rows/statuses and Small Points child orders open the matching inline sorting form
- Sorting form shows entries, allows whole-kg add/edit/delete while editable, and read-only history otherwise
- Master Data: search-as-you-type on every tab, clickable rows, popup create/edit, container edit persistence, medium category filtering
- whole-kg inputs/displays across current and legacy/mobile weight inputs
- WEEE warehouse zeros display blank; negative highlighting remains; major-category separator retained
- Master Data sticky tab bar and current tab/scroll preservation remain active
- root folder and ZIP use the same version name

Automated checks:
- desktop JavaScript: node --check passed
- backend Python compile: passed
- relevant pytest selection: 5 passed, 1 known legacy BIG_BAG test failed (legacy medium no longer active)
- July DB retained: 145 inbound trips, 147 inbound loads, 1,149 sorting entries
