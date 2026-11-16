"""The output stripper behind ``nbpress-strip``, run as a pre-commit hook over dev and published notebooks.

Clears code-cell outputs and execution counts and drops volatile metadata, leaving cell tags alone, so a papermill
``parameters`` cell keeps its tag. Exits 1 when it rewrote a file, which is how pre-commit reports a fixing hook.
Exclude the docs-artifact lane from it: those notebooks are executed on purpose, and their outputs are the content.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CELL_OUTPUT_FIELDS = ("outputs", "execution_count")
NOTEBOOK_METADATA_KEYS_TO_REMOVE = {
    "widgets",
    "signature",
}
CELL_METADATA_KEYS_TO_REMOVE = {
    "execution",
    "collapsed",
    "scrolled",
}


def strip_notebook(path: Path) -> bool:
    """Strip one notebook in place; ``True`` when anything changed."""
    original_text = path.read_text(encoding="utf-8")
    notebook = json.loads(original_text)

    changed = False
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        for field in CELL_OUTPUT_FIELDS:
            if field == "outputs":
                if cell.get(field):
                    cell[field] = []
                    changed = True
            elif cell.get(field) is not None:
                cell[field] = None
                changed = True

        metadata = cell.get("metadata")
        if isinstance(metadata, dict):
            for key in CELL_METADATA_KEYS_TO_REMOVE:
                if key in metadata:
                    metadata.pop(key)
                    changed = True

    metadata = notebook.get("metadata")
    if isinstance(metadata, dict):
        for key in NOTEBOOK_METADATA_KEYS_TO_REMOVE:
            if key in metadata:
                metadata.pop(key)
                changed = True

    if not changed:
        return False

    updated_text = json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"
    path.write_text(updated_text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    """``nbpress-strip NOTEBOOK...``: strip each notebook, exiting 1 when any changed."""
    file_args = [Path(arg) for arg in (sys.argv[1:] if argv is None else argv)]
    changed_paths = [path for path in file_args if strip_notebook(path)]
    if not changed_paths:
        return 0

    for path in changed_paths:
        print(f"Stripped outputs from {path}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
