# Build 2.5.7 Intermediate

## Critical interaction fixes
- Fixed `Νέα Παραλαβή` so it always restores the receipt form to a stable DOM host before opening as a centered draggable popup.
- Fixed sorting forms disappearing/breaking after automatic list refreshes by adding stable hosts for movable inline panels and refresh guards while inline forms are open.
- In Receipts, the order number itself now opens the sorting form for that exact load; row click still opens receipt edit and status click opens sorting.
- In Sorting, the entire order row continues to open the sorting form inline.
- Automatic 4-second refresh no longer destroys an open inline receipt/sorting form.

## UI
- Receipt summary cards expand to available width and avoid wrapping labels while there is enough space.
- Stronger pastel workspace palette while preserving the dark left navigation.

## Data
- Existing July database retained unchanged: 145 trips, 147 loads, 1,149 sorting entries.
