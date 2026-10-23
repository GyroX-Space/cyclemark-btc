# Contributing to CycleMark BTC

Thank you for helping improve CycleMark. All public contributions, documentation, interface text, comments, tests, and generated product outputs must be in English.

## Ground rules

- Do not claim predictive performance without reproducible evidence.
- Do not add fabricated live data or illustrative records to the production archive.
- Never introduce look-ahead bias or silently rewrite published history.
- Keep source attribution, licensing, availability timestamps, and data revisions explicit.
- Do not commit API keys, tokens, private configuration, or data that cannot be redistributed.
- Prefer small, reviewable pull requests with tests.

## Before opening a pull request

1. Explain the problem and the intended behavior.
2. Add or update tests for changes to calculations, data ingestion, schemas, and state logic.
3. Run the test suite locally.
4. Document any methodology or data-source changes.
5. State whether historical output changes and why.
6. Avoid modifying past published signals without an explicit versioned migration.

## Research changes

Any change to feature definitions, normalization, weights, thresholds, labels, or validation methods must include a methodology update and an impact assessment. Performance claims must include the evaluation period, baselines, costs where relevant, uncertainty, and known limitations.

## Style

Use clear English names, type hints where useful, deterministic calculations, explicit exceptions for unavailable data, and UTC timestamps for machine records.
