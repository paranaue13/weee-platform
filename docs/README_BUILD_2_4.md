# WEEE Platform Build 2.4

Registry + searchable Master Data update.

- 84 counterparty registry rows seeded as detailed Partner Master Data.
- 362 unique Supplier Branch rows seeded from the supplied supplier/sub-branch register.
- ~222 supplier tax IDs represented; duplicate rows in the pasted source are not duplicated in the database.
- Added `organization_registry_details` and `supplier_branches` tables.
- Added `/master/suppliers/{id}/branches` and relevance-ranked `/master/organizations-search`.
- Searchable Receiving fields remain free text and dynamically rank relevant matches.
- Android versionCode 24 / versionName 2.4 / cache URL build=2.4.
