# Official decor catalogue discovery

This first integration stage checks public catalogue pages and records source links and image references. It deliberately does **not** bulk-download or republish manufacturer artwork.

## Sources
- NORDECO design: public decor catalogue with detail pages and decor metadata.
- Lamarty: official promotional/catalogue page with PDF and decor-folder links.
- EGGER: official decor-data page; some unwatermarked data packages require a registered myEGGER account. No automated login is used.
- Югра-Плит: source URL is pending verification; do not treat third-party dealer catalogues as the manufacturer's official source.

## Schedule
GitHub Actions runs daily at 02:30 UTC (07:30 Yekaterinburg time) and can be started manually.

## Next steps
1. Inspect the discovery snapshot and identify stable decor-detail endpoints.
2. Confirm image/data reuse terms for each manufacturer or obtain permission.
3. Import allowed reference images into a visual index with manufacturer, decor code/name, collection, surface structure, source URL and checked date.
4. Connect visual matches to `decor-mappings.json`; unverified edge matches must be flagged for human review.
