# 2.5.11 Intermediate

- Existing and new Receipts now open in the same editable draggable popup; removed inline receipt editing.
- Fixed day navigation lock caused by the inline receipt guard; added async request sequence guards for Receipts and Sorting navigation.
- Sorting remains editable in a draggable popup.
- Rebuilt receipt day/month summary as a responsive grid that stacks whole cards instead of clipping tables.
- Replaced decorative dropdown arrows with real clickable dropdown buttons for Carrier, Driver, Vehicle, Supplier, Incoming Container, and Outgoing Container.
- Driver dropdown remains restricted to drivers of the selected carrier; vehicle suggestions remain carrier-scoped.
- Incoming/outgoing container dropdowns show all active containers regardless of carrier; `Προσαρμοσμένο` is first and opens whole-kg tare popup.
- Quick-created containers are automatically selected back into the receipt form.
- DPP continues as annual sequence and restarts at 1 for each report year.
- Sorting photos button remains available below recycler comments.
- Recent pastel UI adjustments and removal of `— από Ταξινόμηση` labels retained.
- Database is preserved; no destructive migration.
