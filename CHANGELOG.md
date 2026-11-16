# Changelog

## 0.1.0

### Added

- `nbpress-publish`, `nbpress-render` and `nbpress-strip`, extracted from interpretune's notebook publisher,
  docs-artifact renderer and output-stripping hook, and configured from `[tool.nbpress]`. The earlier table names
  `[tool.notebook-publishing]` and `[tool.interpretune.notebooks]` are still read.
- pre-commit hooks `nbpress-strip`, `nbpress-publish` and `nbpress-check-stale`.
- The renderer writes paths into any checkout of the repository (the one it runs in, a sibling worktree, a CI job
  directory) repository-relative in artifact outputs, and `--check-stale` fails, naming the path, on an artifact that
  still carries one. Previously only the user's home root was replaced, so working-copy names reached the docs.
