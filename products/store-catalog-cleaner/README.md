# Store Catalog Cleaner

A standalone, offline-first browser utility for checking and cleaning CSV product and inventory catalogs before import into another system.

## What it does

- Opens a local CSV file or loads a sample catalog.
- Detects common delimiters (comma, semicolon, tab, pipe).
- Handles quoted fields, escaped quotes, commas inside cells, and Windows/Unix line endings.
- Reports blank rows, exact duplicate rows, missing values by column, and non-numeric values in columns whose names include price, cost, or amount.
- Trims cell whitespace, normalizes headers, removes blank rows, and optionally removes duplicate values using a selected column (SKU/ID is preselected when detected).
- Previews up to 50 rows and exports the full cleaned CSV.
- Keeps the original working copy available through Restore original.

## Run

Open index.html in a modern browser. No installation, account, network connection, server, API key, or subscription is required.

## Privacy

Files are read and processed locally in the browser. The app contains no analytics, trackers, external scripts, or upload requests. Do not close the tab before downloading the cleaned result.

## Limits

- CSV only; Excel workbooks (.xlsx) are not supported.
- Up to 15 MB, 100,000 data rows, and 200 columns.
- Numeric checks are format checks, not tax/accounting validation.
- This is a generic CSV cleaner, not a certified Shopify, WooCommerce, or other platform import validator. Check the target platform's current import schema before importing.
- Always retain a backup of the original file.

## Sample

Use the built-in sample button to test trimming, duplicate SKU removal, blank-row removal, header normalization, and price checks.

## License

The product source is original project code. The repository's project license applies; review that license before redistribution.
