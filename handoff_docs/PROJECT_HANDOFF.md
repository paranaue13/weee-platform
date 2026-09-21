# WEEE Platform — project handoff

## 1. Product purpose
WEEE Platform is a Windows/Android operational system for a Greek WEEE (ΑΗΗΕ) recycling company. It is intended to replace Excel/paper workflows, synchronize operational data, and ultimately integrate with the Galaxy ERP.

The immediate priority is a reliable tool for the user's own daily work. A future commercial product is a real possibility, so avoid needless hard-coding, duplicate business logic, and schema decisions that block multi-company use later.

## 2. Main workflow
The operational flow is:

**Παραλαβή → Ταξινόμηση → Αποθήκη ΑΗΗΕ → Παραγωγή → Έτοιμα Υλικά → Φορτώσεις**

Supporting modules include Βιβλίο Διακίνησης, Galaxy integration areas, and Μητρώα.

### Receiving types
- **Container**: first weighing, full container left, empty container taken, second weighing, net weight.
- **Καρότσα / trailer / flatbed**: first weighing, unload, second weighing, net weight.
- **Μικρά Σημεία**: truck weighed as a whole and carries multiple individual orders; each order may be handled/classified separately.

## 3. Roles / operational areas
Roles discussed include Logistics, Sorting/Production, Loading point, Administration/Management. User/role controls must remain separate from profile information.

## 4. Current codebase
Authoritative source archive: `weee_platform_build_2_5_35_intermediate.zip`.

Persistent Windows database is intended to live outside the build so registry edits survive intermediate upgrades:
`%LOCALAPPDATA%\WEEE Platform\data\weee_dev.db`

Do not bundle `.venv` in releases. Launcher logic was changed previously to call `.venv\Scripts\python.exe` directly and create the venv if missing rather than relying on `activate.bat`.

## 5. Build 2.5.35 context
Build 2.5.35 was produced after the user reported:
- small tab-loading delay in Receipts/Sorting/Warehouse/Production;
- first click on another Registry subtab returned to the first registry tab;
- warehouse stock arithmetic displayed negative balances because historical sorting movements were dated incorrectly;
- refresh icon looked like a browser reload icon;
- Registries did not match the agreed visual system.

2.5.35 introduced a targeted pass for tab reuse/cache/prefetch, registry initial-tab state, global refresh behavior, and warehouse historical movement dating/carry-in handling. Treat those changes as current code, but verify behavior before building further.

## 6. Key functional philosophy
- Sorting is a separate module from Receipts. Do not merge them.
- Data shown in different modules must come from canonical records, not copied descriptions.
- ΑΗΗΕ and Υλικά should be canonical profiles used throughout the application.
- Historical data must remain reproducible from source imports.
- User-facing operators should see clear operational labels; internal six-digit codes should not be shown unnecessarily in operator-facing Android sorting screens.

## 7. Current top-level Registries
Desired Registry tabs/order:
**Προμηθευτές | Πελάτες | Μεταφορείς | Συνεργάτες | Containers | Μέσα συλλογής | ΑΗΗΕ | Υλικά | Τμήματα | Εργαζόμενοι**

All Registry tabs should use the same visual/table system and soft-deletion behavior.
