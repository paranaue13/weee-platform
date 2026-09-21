# WEEE Platform — business rules

## 1. Receipts and sorting
Receipt/order number is the Excel `Αριθμός Εντολής`. Historical source workbooks do not provide a reliable arrival time; **never invent a time**.

Historical classification rules used for the Jan–Aug import include:
- all Soultanoglou → Μικρά Σημεία;
- Samaras/Perkas with mass >= 2,000 kg → Καρότσα/Trailer;
- Cosmote > 4,000 kg → Καρότσα/Trailer;
- otherwise a valid container → Container, else Καρότσα/Trailer.

Missing first/second weighings or container-in/out values are allowed in historical records.

## 2. WEEE warehouse arithmetic
For each WEEE code and selected month, the processing stock must obey the business identity:

**Opening stock + classified receipts − processing = stock awaiting processing**

Shipment-side flows must be handled separately and must not be mixed into processing stock.

Historical production can exceed classifications available in the 2026 receipt import because physical stock existed before the imported period. Do not fabricate a prior stock value. If a genuine opening-stock source is unavailable, represent the necessary carry-in explicitly and clearly rather than silently hiding negatives.

Carry-forward opening stock equals the actual closing stock of the previous calendar month.

Do not merge distinct official WEEE codes. Only internal company subcategories that share one displayed official/parent code may be aggregated for display.

## 3. Production provenance
Production must retain provenance:
- `HERMES`
- `OTHER` / Λοιποί

HERMES is a subset of total production, not additional to it.

Negative production corrections always reduce **OTHER**, never HERMES.

Correct August 2026 production total from the authoritative source is:
- Total: **130,442 kg**
- HERMES: **7,134 kg**
- OTHER: **123,308 kg**

This is a mandatory regression value.

## 4. Production hierarchy
Production by WEEE must support the hierarchy:
**major category → official subcategory → internal company subcategory**

Category 1 label is **Κλιματιστικά**.

Expanded child columns must not double-count the total. Expanding/collapsing is a display operation only; period totals must remain unchanged.

The Registry should eventually control whether a WEEE profile is `Προς επεξεργασία: Ναι/Όχι`. Production should show only processable codes rather than relying on hard-coded exclusions.

## 5. Canonical WEEE profile
The canonical **ΑΗΗΕ** profile should contain:
- Κωδικός
- Επίσημη Περιγραφή
- Περιγραφή HER (HER = Hellenic Environmental Recycling, the user's company name in English)
- Κωδικός ΕΚΑ
- processability / `Προς επεξεργασία` flag where implemented

The UI may visually combine official code + official description in compact views, but they remain separate data fields.

## 6. Canonical Material profile
The canonical **Υλικό** profile should contain:
- Κωδικός ERP (Galaxy)
- Γένος (e.g. Μέταλλα, Πλαστικά, CRT, etc.)
- Επίσημη Περιγραφή
- Κωδικός Reptool
- Περιγραφή HER
- Κωδικός ΕΚΑ
- active/inactive status derived from ERP code rule
- export quantity increment / precision rule

### Active material rule
**A Material is active only if it has a non-empty ERP/Galaxy code.**
A row without ERP code may remain in the canonical registry for reference/mapping but is inactive and must not appear in normal operational selectors.

Do not treat `Περιγραφή ERP` as a substitute for ERP code.

### Precious materials rule
Materials whose HER description is exactly/semantically the category:
**`Πλακέτες τυπ/νών κυκλωμάτων >10cm²`**
are considered **precious (`Πολύτιμα`)**.

Export quantity increment:
- precious material: **0.05 kg (50 g)**
- all other export materials: **0.5 kg (500 g)**

This should be a property/business rule attached to the Material profile so all shipment/export validation uses the same rule.

## 7. HERMES monthly processing reporting
HERMES is a supplier/provenance category, not a processing method.
If 125 kg of a WEEE class was processed and 26 kg came from HERMES, normal/OTHER report is 99 kg and HERMES report is 26 kg.

## 8. Collection media
Do not reintroduce `METAL_BASKET` as a usable seeded collection type. Legacy compatibility filters may remain if required by old data.

## 9. Quarter close
At the end of each calendar quarter there must be inventory/mass-balance capability. Reports are needed by day, month, quarter and year.
