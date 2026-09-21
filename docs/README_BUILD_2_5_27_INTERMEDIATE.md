# WEEE Platform 2.5.27 Intermediate

Corrective UI/runtime build.

- Responsive Receipts/Sorting workspace: daily data keeps priority; right calendar/filter rail shrinks first.
- Sorting popup table header is scoped to its own scroll container and resets at the top when opened.
- Registry inactive records remain visible and are highlighted with light pastel terracotta; supported registries can be reactivated.
- Settings icon replaced with a consistent gear/cog line icon.
- Windows launcher no longer calls activate.bat; it uses the local venv Python executable directly and validates venv creation.
- WEEE Warehouse uses a more compact current-inventory layout, larger table viewport, and aggregates internal subcategories to the displayed parent/official code.
- User-supplied WEEE logo is embedded in the sidebar branding.

Bundled operational data remains unchanged: 1,077 receipts / 1,077 sorting sessions / 8,279 sorting entries, through 31 Aug 2026.
