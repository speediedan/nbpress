"""The publisher (``nbpress-publish``), driven against throwaway consuming repositories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nbpress.publish import (
    HASH_FILE,
    NotebookConfigError,
    PublisherConfig,
    compute_file_hash,
    load_notebook,
    main,
)


def _notebook(*cells):
    return {"cells": list(cells), "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


def _code(text, tags=()):
    return {
        "cell_type": "code",
        "metadata": {"tags": list(tags)},
        "source": text.splitlines(keepends=True),
        "outputs": [],
        "execution_count": None,
    }


BASE_TABLE = (
    'dev_dir = "examples/dev"\npublish_dir = "examples/publish"\ncolab_repo = "org/adapter"\n'
    'install_cell = ["# %pip install adapter"]\n'
)


def _repo(tmp_path: Path, table: str = "", *, header: str = "[tool.nbpress]", base: str = BASE_TABLE) -> Path:
    root = tmp_path / "adapter"
    (root / "examples" / "dev" / "nested").mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "0"\n\n{header}\n' + base + table)
    nb = _notebook(
        _code("from examples.dev.helpers import h\n"),
        _code("secret = 1\n", tags=["remove-cell"]),
        _code("%pip install nothing\nimport json\n"),
    )
    (root / "examples" / "dev" / "nested" / "demo.ipynb").write_text(json.dumps(nb))
    (root / "examples" / "dev" / "helpers.py").write_text("h = 1\n")
    (root / "examples" / "dev" / "__pycache__").mkdir()
    (root / "examples" / "dev" / "__pycache__" / "helpers.cpython-313.pyc").write_bytes(b"\x00")
    return root


class TestPublisher:
    def test_publishes_transforms_and_tracks_hashes(self, tmp_path, capsys):
        root = _repo(tmp_path, table='[tool.nbpress.import_rewrites]\n"examples.dev." = "examples.publish."\n')
        assert main(["--root", str(root)]) == 0
        published = root / "examples" / "publish" / "nested" / "demo.ipynb"
        cells = load_notebook(published)["cells"]
        assert [c["metadata"].get("id") for c in cells[:2]] == ["colab-badge", "install-deps"]
        assert "github/org/adapter/blob/main/examples/publish/nested/demo.ipynb" in "".join(cells[0]["source"])
        # the rewritten cell keeps the list-of-lines form, and its final line carries no newline
        assert "".join(cells[2]["source"]) == "from examples.publish.helpers import h"
        assert len(cells) == 4, "the remove-cell tagged cell must be gone"
        assert (root / "examples" / "publish" / "helpers.py").read_text() == "h = 1\n"
        assert not list((root / "examples" / "publish").rglob("*.pyc")), "bytecode caches are never publication inputs"
        hashes = json.loads((root / "examples" / "publish" / HASH_FILE).read_text())
        assert set(hashes) == {"examples/dev/nested/demo.ipynb", "examples/dev/helpers.py"}
        # a second pass is a no-op, and --check-only agrees
        assert main(["--root", str(root), "--check-only"]) == 0
        capsys.readouterr()
        assert main(["--root", str(root)]) == 0
        assert "All files are up to date" in capsys.readouterr().out

    def test_republishing_an_unchanged_notebook_reproduces_it_byte_for_byte(self, tmp_path):
        root = _repo(tmp_path)
        assert main(["--root", str(root)]) == 0
        published = root / "examples" / "publish" / "nested" / "demo.ipynb"
        first = published.read_bytes()
        assert main(["--root", str(root), "--force"]) == 0
        assert published.read_bytes() == first

    def test_check_only_names_the_stale_file_and_force_republishes_everything(self, tmp_path, capsys):
        root = _repo(tmp_path)
        assert main(["--root", str(root)]) == 0
        (root / "examples" / "dev" / "helpers.py").write_text("h = 2\n")
        assert main(["--root", str(root), "--check-only"]) == 1
        assert "examples/dev/helpers.py" in capsys.readouterr().out
        assert main(["--root", str(root), "--force", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert out.count("WOULD ") == 2 and "pyc" not in out
        assert (root / "examples" / "publish" / "helpers.py").read_text() == "h = 1\n", "dry run must not write"

    def test_install_cell_and_branch_come_from_the_table(self, tmp_path):
        base = BASE_TABLE.replace('"# %pip install adapter"', '"%pip install adapter[examples]"')
        root = _repo(tmp_path, table='colab_branch = "release"\n', base=base)
        cfg = PublisherConfig.from_pyproject(root)
        assert cfg.colab_branch == "release" and cfg.install_cell == ("%pip install adapter[examples]\n",)
        assert main(["--root", str(root)]) == 0
        cells = load_notebook(root / "examples" / "publish" / "nested" / "demo.ipynb")["cells"]
        assert cells[1]["source"] == ["%pip install adapter[examples]\n"]
        assert "/blob/release/" in "".join(cells[0]["source"])

    def test_the_root_defaults_to_the_nearest_pyproject(self, tmp_path, monkeypatch):
        root = _repo(tmp_path)
        monkeypatch.chdir(root / "examples" / "dev" / "nested")
        assert main([]) == 0
        assert (root / "examples" / "publish" / "nested" / "demo.ipynb").is_file()

    def test_hashes_ignore_line_ending_rewrites(self, tmp_path):
        """A CRLF checkout of the same file must hash as the LF original, or Windows reports everything stale."""
        lf = tmp_path / "lf.py"
        crlf = tmp_path / "crlf.py"
        lf.write_bytes(b"a = 1\nb = 2\n")
        crlf.write_bytes(b"a = 1\r\nb = 2\r\n")
        assert compute_file_hash(lf) == compute_file_hash(crlf)
        other = tmp_path / "other.py"
        other.write_bytes(b"a = 1\nb = 3\n")
        assert compute_file_hash(lf) != compute_file_hash(other)
        # a binary file with an incidental CRLF byte pair hashes raw: a checkout never rewrites it
        png = tmp_path / "img.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
        assert compute_file_hash(png) == hashlib.sha256(png.read_bytes()).hexdigest()

    def test_a_missing_dev_dir_is_an_error(self, tmp_path, capsys):
        root = _repo(tmp_path, base=BASE_TABLE.replace('"examples/dev"', '"nope"'))
        assert main(["--root", str(root)]) == 1
        assert "dev directory not found" in capsys.readouterr().out


class TestTableContract:
    """The publisher holds no repository defaults, so the table is refused by name rather than half-read."""

    @pytest.mark.parametrize("legacy", ["[tool.notebook-publishing]", "[tool.interpretune.notebooks]"])
    def test_each_legacy_table_name_is_read_identically(self, tmp_path, legacy):
        new = PublisherConfig.from_pyproject(_repo(tmp_path / "new"))
        old = PublisherConfig.from_pyproject(_repo(tmp_path / "old", header=legacy))
        assert (new.dev_dir.name, new.colab_repo, new.install_cell) == (
            old.dev_dir.name,
            old.colab_repo,
            old.install_cell,
        )

    @pytest.mark.parametrize("second", ["[tool.notebook-publishing]", "[tool.interpretune.notebooks]"])
    def test_two_tables_are_refused_rather_than_merged(self, tmp_path, capsys, second):
        root = _repo(tmp_path, table=f"\n{second}\n" + BASE_TABLE)
        with pytest.raises(NotebookConfigError, match="keep one"):
            PublisherConfig.from_pyproject(root)
        assert main(["--root", str(root)]) == 1
        out = capsys.readouterr().out
        assert "[tool.nbpress]" in out and second in out

    @pytest.mark.parametrize("dropped", ["dev_dir", "publish_dir", "colab_repo", "install_cell"])
    def test_a_missing_required_key_is_refused_by_name(self, tmp_path, dropped):
        base = "".join(line + "\n" for line in BASE_TABLE.splitlines() if not line.startswith(dropped))
        with pytest.raises(NotebookConfigError, match=dropped):
            PublisherConfig.from_pyproject(_repo(tmp_path, base=base))

    def test_an_unknown_key_is_refused_by_name(self, tmp_path):
        """A misspelled optional key would otherwise fall back to its default without a word."""
        with pytest.raises(NotebookConfigError, match="colab_brnach"):
            PublisherConfig.from_pyproject(_repo(tmp_path, table='colab_brnach = "release"\n'))

    def test_no_table_is_refused(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        with pytest.raises(NotebookConfigError, match="no \\[tool.nbpress\\] table"):
            PublisherConfig.from_pyproject(tmp_path)

    def test_no_pyproject_is_refused(self, tmp_path):
        with pytest.raises(NotebookConfigError, match="no pyproject.toml"):
            PublisherConfig.from_pyproject(tmp_path)

    def test_hash_keys_are_relative_to_the_configured_base(self, tmp_path):
        cfg = PublisherConfig.from_pyproject(_repo(tmp_path, table='hash_key_base = "examples"\n'))
        assert cfg.hash_key(cfg.dev_dir / "nested" / "demo.ipynb") == "dev/nested/demo.ipynb"
