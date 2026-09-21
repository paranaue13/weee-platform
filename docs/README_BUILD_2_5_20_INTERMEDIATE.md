# WEEE Platform 2.5.20 Intermediate

- Unified Windows-style scale and spacing across the application.
- Receipts: table stays beside the calendar, with responsive scale and right-side filters.
- Sorting: unified layout while retaining row click -> sorting sheet/popup.
- Registries: existing searchable lists, create/edit/delete popup behavior retained.
- Persistent Windows data storage: from this build onward SQLite data is stored at
  `%LOCALAPPDATA%\WEEE Platform\data\weee_dev.db`.
  Replacing the application folder with a later build will therefore not overwrite registry/receipt changes.
