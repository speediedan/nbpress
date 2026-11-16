# Changelog

## 0.1.0

### Added

- `nbpress-publish`, `nbpress-render` and `nbpress-strip`, extracted from interpretune's notebook publisher,
  docs-artifact renderer and output-stripping hook, and configured from `[tool.nbpress]`. The earlier table names
  `[tool.notebook-publishing]` and `[tool.interpretune.notebooks]` are still read.
- pre-commit hooks `nbpress-strip`, `nbpress-publish` and `nbpress-check-stale`.
