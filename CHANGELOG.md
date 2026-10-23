# Changelog

Notable project changes are recorded here. This project is in early research development; entries do not imply predictive validity.

## Unreleased

- Established a raw-market-data-first governance rule for all core scores.
- Removed Alternative.me Fear & Greed from BFS calculations; it is retained only as optional auxiliary display context.
- Reduced prototype BFS configured-weight coverage from 60% to 40% because only price-derived cycle-position and trend dimensions are currently implemented.
- Clarified that third-party calculated indicators, including provider-computed valuation metrics, are not core inputs by default.
- Updated methodology and data-source documentation to require explicit exceptions, versioning, and validation before third-party derived indicators can affect scores.

## 0.1.0

- Added public BTC market-data ingestion and provisional BFS research scaffolding.
- Added daily archive, historical research backfill, static dashboard, AWS runner, and documentation.
- BOS and composite state remain withheld pending complete features and validation.
