"""The docs-artifact renderer (``nbpress-render``), driven against throwaway consuming repositories."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nbpress import render as engine


def _notebook(output_lines: list[str] | None = None, source: str = "x = 1\n") -> dict:
    return {
        "cells": [
            {
                "cell_type": "code",
                "source": [source],
                "outputs": [{"output_type": "stream", "name": "stdout", "text": output_lines or []}],
                "metadata": {},
            }
        ],
        "metadata": {},
    }


def _repo(tmp_path: Path, *, extra: str = "", hooks_path: Path | None = None) -> Path:
    """A throwaway consuming repository: a publish lane, an artifact lane, and the table naming them."""
    root = tmp_path / "consumer"
    (root / "publish" / "lane").mkdir(parents=True)
    (root / "artifacts").mkdir()
    table = (
        '[tool.nbpress]\ndev_dir = "dev"\npublish_dir = "publish"\ncolab_repo = "org/consumer"\n'
        'install_cell = ["# %pip install consumer"]\ndocs_artifact_dir = "artifacts"\n'
        'docs_render_command = "python scripts/notebook_docs.py"\n'
    )
    if hooks_path is not None:
        table += f"docs_hooks = {json.dumps(str(hooks_path))}\n"
    (root / "pyproject.toml").write_text(table + extra)
    return root


def _write(path: Path, notebook: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notebook), encoding="utf-8")


class TestStandardLibraryOnly:
    def test_nothing_but_the_standard_library_is_imported(self):
        """The pre-commit and docs jobs run these before any dependency is installed; papermill is execution-only."""
        probe = (
            "import sys\nbefore = set(sys.modules)\n"
            "import nbpress.publish, nbpress.render, nbpress.strip\n"
            "extra = sorted(m.split('.')[0] for m in set(sys.modules) - before)\n"
            "third_party = sorted({m for m in extra if m != 'nbpress' and m not in sys.stdlib_module_names "
            "and not m.startswith('_')})\n"
            "assert not third_party, third_party\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


class TestSourceComparator:
    def test_source_drift_is_detected_and_outputs_are_ignored(self):
        artifact = _notebook(["ran\n"])
        assert engine.artifact_matches_source(artifact, _notebook())
        assert not engine.artifact_matches_source(artifact, _notebook(source="x = 2\n"))


class TestDriftExitCodeContract:
    """A caller must be able to tell "an artifact drifted" from "the check failed to run": both exit non-zero."""

    def test_drift_code_avoids_the_codes_it_must_be_distinguishable_from(self):
        """0/1/2 are already spoken for, and 2 (argparse's usage error, which runs before `main()`) is easy to
        miss."""
        assert engine.DRIFT_EXIT_CODE not in (0, 1, 2)

    def test_argparse_usage_error_is_not_reported_as_drift(self):
        """The collision above, measured rather than assumed."""
        result = subprocess.run([sys.executable, "-m", "nbpress.render", "--bogus-flag"], capture_output=True)
        assert result.returncode == 2, "argparse's usage convention changed; re-check DRIFT_EXIT_CODE"
        assert result.returncode != engine.DRIFT_EXIT_CODE


class TestMissingArtifactIsDrift:
    """A published notebook with no artifact renders code-only on a docs site with no error anywhere."""

    def test_a_published_notebook_with_no_artifact_fails_the_check_by_name(self, tmp_path, capsys):
        """Positive control: the check can fire on exactly the planted absence, naming the configured command."""
        root = _repo(tmp_path)
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())
        assert engine.main(["--check-stale"], root=root) == engine.DRIFT_EXIT_CODE
        err = capsys.readouterr().err
        # The path is printed in the platform's own spelling (a backslash on Windows), so compare that form.
        assert "MISSING artifact" in err and str(Path("lane") / "nb.ipynb") in err
        assert "python scripts/notebook_docs.py --notebook nb" in err

    def test_a_present_matching_artifact_passes(self, tmp_path, capsys):
        """Negative control on the same fixture: presence is the only thing that changed."""
        root = _repo(tmp_path)
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())
        _write(root / "artifacts" / "lane" / "nb.ipynb", _notebook())
        assert engine.main(["--check-stale"], root=root) == 0
        assert "MISSING artifact" not in capsys.readouterr().err

    def test_a_source_drifted_artifact_fails_the_check_by_name(self, tmp_path, capsys):
        root = _repo(tmp_path)
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook(source="x = 2\n"))
        _write(root / "artifacts" / "lane" / "nb.ipynb", _notebook())
        assert engine.main(["--check-stale"], root=root) == engine.DRIFT_EXIT_CODE
        assert "STALE artifact (rebuild it)" in capsys.readouterr().err


class TestSkippedSectionIsDrift:
    """An enabled section that skipped at render time ships as a `[SKIPPED]` line where the docs show its output."""

    SKIP_LINE = "[SKIPPED] remote section: could not pull owner/collection: 404"
    # The SOURCE carries the print that produces the marker in every case, so the check can only be keyed on outputs.
    SOURCE = 'print("[SKIPPED] remote section: ...")\n'

    def _plant(self, tmp_path: Path, artifact_output: list[str]) -> Path:
        root = _repo(tmp_path)
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook([], self.SOURCE))
        _write(root / "artifacts" / "lane" / "nb.ipynb", _notebook(artifact_output, self.SOURCE))
        return root

    def test_a_skipped_section_in_the_outputs_fails_the_check_by_name(self, tmp_path, capsys):
        root = self._plant(tmp_path, ["pulled nothing\n", self.SKIP_LINE + "\n"])
        assert engine.main(["--check-stale"], root=root) == engine.DRIFT_EXIT_CODE
        err = capsys.readouterr().err
        assert "SKIPPED section in artifact" in err and self.SKIP_LINE in err and str(Path("lane") / "nb.ipynb") in err

    def test_the_marker_in_source_alone_passes(self, tmp_path, capsys):
        root = self._plant(tmp_path, ["pulled owner/collection @ 872760c7\n"])
        assert engine.main(["--check-stale"], root=root) == 0
        assert "SKIPPED section" not in capsys.readouterr().err

    def test_the_marker_inside_a_line_does_not_count(self, tmp_path):
        """Only a line that STARTS with the marker is a skip announcement; prose quoting it is not."""
        root = self._plant(tmp_path, ["the cell prints [SKIPPED] when the pull fails\n"])
        assert engine.main(["--check-stale"], root=root) == 0


class TestHostPathNormalization:
    """An artifact must not publish the identity of whoever rendered it."""

    MARKERS = ("examples/publish/", "docs/notebook_artifacts/")

    def test_rewrites_the_users_root_wherever_it_lives(self):
        rx = engine._user_root_pattern("someuser")
        for original in (
            "/home/someuser/repos/project/src/project/config/shared.py:222: UserWarning",
            "/mnt/cache/someuser/worktrees/scratch/src/project/analysis/core.py",
            "/mnt/cache_extended/someuser/.cache/huggingface/hub",
            "/mnt/cache/someuser/.venvs/dev/lib/python3.13/site-packages/x.py",
            '  File "/home/someuser/repos/x/y.py", line 3',
        ):
            assert rx.sub("~/", original) != original, original
            assert "someuser" not in rx.sub("~/", original)

    def test_leaves_hub_and_git_references_alone(self):
        """`owner/repo` names real published repositories; rewriting them would break working references."""
        rx = engine._user_root_pattern("someuser")
        for untouched in (
            "Downloading from huggingface.co/someuser/rte to cache",
            "https://huggingface.co/someuser/steering_ops",
            "see https://github.com/someuser/project/pull/1",
            "resolves to someuser.concept_direction_ops.concept",
            "models--someuser--concept_direction_ops/116271f2",
            "repo_id='someuser/trivial_op_repo'",
        ):
            assert rx.sub("~/", untouched) == untouched, untouched

    def test_a_url_is_not_a_path_even_after_a_double_slash(self):
        rx = engine._user_root_pattern("someuser")
        url = "see https://github.com/someuser/project/pull/1"
        assert rx.sub("~/", url) == url

    def test_papermill_metadata_becomes_repo_relative(self):
        notebook = {
            "cells": [],
            "metadata": {
                "papermill": {
                    "input_path": "/mnt/cache/someuser/worktrees/scratch/examples/publish/a.ipynb",
                    "output_path": "/home/someuser/repos/project/docs/notebook_artifacts/a.ipynb",
                }
            },
        }
        assert engine.normalize_host_paths(notebook, markers=self.MARKERS, user="someuser") == 2
        pm = notebook["metadata"]["papermill"]
        assert pm["input_path"] == "examples/publish/a.ipynb"
        assert pm["output_path"] == "docs/notebook_artifacts/a.ipynb"

    def test_normalizes_output_text_and_is_idempotent(self):
        """Idempotence is what lets this run on EVERY write, including `--no-execute`, without churn."""
        notebook = {
            "cells": [
                {"cell_type": "code", "outputs": [{"text": ["/home/someuser/repos/project/src/x.py:9: UserWarning\n"]}]}
            ],
            "metadata": {},
        }
        assert engine.normalize_host_paths(notebook, markers=self.MARKERS, user="someuser") == 1
        assert notebook["cells"][0]["outputs"][0]["text"] == ["~/repos/project/src/x.py:9: UserWarning\n"]
        assert engine.normalize_host_paths(notebook, markers=self.MARKERS, user="someuser") == 0

    def test_markers_come_from_the_configured_lanes(self, tmp_path):
        cfg = engine.DocsConfig.from_pyproject(_repo(tmp_path))
        assert cfg.path_markers == ("publish/", "artifacts/")


class TestGenericConsumer:
    """A repository with no hooks gets the generic behavior."""

    def test_strip_only_render_drops_excluded_cells_and_adds_no_repository_metadata(self, tmp_path):
        root = _repo(tmp_path)
        source = _notebook()
        source["cells"][:0] = [
            {"cell_type": "code", "metadata": {"id": "install-deps"}, "source": ["# %pip install x"], "outputs": []},
            {"cell_type": "code", "metadata": {"tags": ["injected-parameters"]}, "source": ["n = 2"], "outputs": []},
        ]
        _write(root / "publish" / "lane" / "nb.ipynb", source)
        (root / "publish" / "lane" / "asset.png").write_bytes(b"\x89PNG")
        assert engine.main(["--no-execute"], root=root) == 0
        written = json.loads((root / "artifacts" / "lane" / "nb.ipynb").read_text())
        assert [c["source"] for c in written["cells"]] == [["x = 1\n"]]
        assert written["metadata"] == {}, "no hooks, so no stamp"
        assert (root / "artifacts" / "lane" / "asset.png").read_bytes() == b"\x89PNG"
        assert engine.main(["--check-stale"], root=root) == 0

    def test_a_failed_execution_discards_the_partial_artifact(self, tmp_path, monkeypatch, capsys):
        """A half-executed notebook would otherwise render its traceback on the docs page as the real output."""
        root = _repo(tmp_path)
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())

        def failing_execute(source, target, timeout, parameters):
            _write(target, _notebook(["Traceback ...\n"]))
            raise RuntimeError("kernel died")

        monkeypatch.setattr(engine, "execute", failing_execute)
        assert engine.main([], root=root) == 1
        assert not (root / "artifacts" / "lane" / "nb.ipynb").exists()
        assert "kernel died" in capsys.readouterr().err

    def test_list_reports_each_artifact_state(self, tmp_path, capsys):
        root = _repo(tmp_path)
        for name in ("missing", "bare", "executed"):
            _write(root / "publish" / "lane" / f"{name}.ipynb", _notebook())
        bare = _notebook()
        bare["cells"][0]["outputs"] = []
        _write(root / "artifacts" / "lane" / "bare.ipynb", bare)
        _write(root / "artifacts" / "lane" / "executed.ipynb", _notebook(["ran\n"]))
        assert engine.main(["--list"], root=root) == 0
        lines = {line.split()[-1]: line for line in capsys.readouterr().out.splitlines()}
        assert "MISSING" in lines[str(Path("lane") / "missing.ipynb")]
        assert "no outputs" in lines[str(Path("lane") / "bare.ipynb")]
        assert "executed" in lines[str(Path("lane") / "executed.ipynb")]

    def test_restamp_without_a_restamp_hook_is_refused_by_name(self, tmp_path, capsys):
        root = _repo(tmp_path)
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())
        assert engine.main(["--restamp"], root=root) == 1
        assert "needs a docs_hooks file whose HOOKS define restamp" in capsys.readouterr().err

    def test_a_missing_artifact_dir_key_is_refused_by_name(self, tmp_path, capsys):
        root = tmp_path / "bare"
        root.mkdir()
        (root / "pyproject.toml").write_text('[tool.nbpress]\npublish_dir = "publish"\n')
        assert engine.main(["--check-stale"], root=root) == 1
        assert "docs_artifact_dir" in capsys.readouterr().err

    def test_the_legacy_table_name_configures_the_renderer_too(self, tmp_path):
        root = _repo(tmp_path)
        pyproject = root / "pyproject.toml"
        pyproject.write_text(pyproject.read_text().replace("[tool.nbpress]", "[tool.notebook-publishing]"))
        assert engine.DocsConfig.from_pyproject(root).artifact_dir == root / "artifacts"


class TestHookContract:
    """A hook the renderer would never call is refused, or its check would pass forever."""

    @staticmethod
    def _hooks_file(tmp_path: Path, body: str) -> Path:
        path = tmp_path / "hooks.py"
        path.write_text(body)
        return path

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ("HOOKS = {'chek': lambda *a, **k: []}\n", "unknown hook(s) ['chek']"),
            ("def check(*a, **k):\n    return []\n", "defines no HOOKS dict"),
            ("HOOKS = {'check': 'not a function'}\n", "are not callable"),
        ],
    )
    def test_malformed_hooks_are_refused_by_name(self, tmp_path, capsys, body, message):
        root = _repo(tmp_path, hooks_path=self._hooks_file(tmp_path, body))
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())
        assert engine.main(["--check-stale"], root=root) == 1
        assert message in capsys.readouterr().err

    def test_a_hooks_path_that_is_not_a_file_is_refused(self, tmp_path, capsys):
        root = _repo(tmp_path, hooks_path=tmp_path / "absent.py")
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())
        assert engine.main(["--check-stale"], root=root) == 1
        assert "which is not a file" in capsys.readouterr().err

    def test_hook_findings_fail_or_note_by_kind_and_stamp_runs_on_write(self, tmp_path, capsys):
        body = (
            "def check(artifact, *, rel, output_text):\n"
            "    return [('drift', f'CUSTOM drift: {rel}')] if 'bad' in output_text else [('note', f'note: {rel}')]\n"
            "def stamp(notebook):\n"
            "    notebook.setdefault('metadata', {})['consumer_stamp'] = 1\n"
            "HOOKS = {'check': check, 'stamp': stamp}\n"
        )
        root = _repo(tmp_path, hooks_path=self._hooks_file(tmp_path, body))
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())
        assert engine.main(["--no-execute"], root=root) == 0
        assert json.loads((root / "artifacts" / "lane" / "nb.ipynb").read_text())["metadata"] == {"consumer_stamp": 1}
        assert engine.main(["--check-stale"], root=root) == 0, "a note alone must not fail the check"
        assert "note: " in capsys.readouterr().err
        _write(root / "artifacts" / "lane" / "nb.ipynb", _notebook(["bad\n"]))
        assert engine.main(["--check-stale"], root=root) == engine.DRIFT_EXIT_CODE
        assert "CUSTOM drift" in capsys.readouterr().err

    def test_a_check_finding_of_unknown_kind_is_refused(self, tmp_path):
        body = "HOOKS = {'check': lambda artifact, *, rel, output_text: [('warning', 'x')]}\n"
        root = _repo(tmp_path, hooks_path=self._hooks_file(tmp_path, body))
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())
        _write(root / "artifacts" / "lane" / "nb.ipynb", _notebook())
        with pytest.raises(engine.NotebookConfigError, match="kind 'warning'"):
            engine.main(["--check-stale"], root=root)

    def test_restamp_applies_restamped_and_reports_refused(self, tmp_path, capsys):
        body = (
            "def restamp(artifact, *, output_text):\n"
            "    if 'dead' in output_text:\n"
            "        return 'refused', 'outputs need a re-execute'\n"
            "    artifact['metadata']['stamp'] = 2\n"
            "    return 'restamped', ''\n"
            "HOOKS = {'restamp': restamp}\n"
        )
        root = _repo(tmp_path, hooks_path=self._hooks_file(tmp_path, body))
        for name, out in (("dead", ["dead\n"]), ("fine", ["ok\n"])):
            _write(root / "publish" / "lane" / f"{name}.ipynb", _notebook(out))
            _write(root / "artifacts" / "lane" / f"{name}.ipynb", _notebook(out))
        assert engine.main(["--restamp"], root=root) == 1
        assert f"REFUSED {Path('lane') / 'dead.ipynb'}" in capsys.readouterr().err
        assert json.loads((root / "artifacts" / "lane" / "fine.ipynb").read_text())["metadata"] == {"stamp": 2}
        assert json.loads((root / "artifacts" / "lane" / "dead.ipynb").read_text())["metadata"] == {}


class TestDocsParameters:
    """A consumer supplies papermill parameters per notebook from its table, and the CLI overrides them."""

    def test_table_parameters_reach_papermill_and_the_cli_overrides_them(self, tmp_path, monkeypatch):
        root = _repo(tmp_path, extra='[tool.nbpress.docs_parameters."lane/nb"]\nepochs = 1\nname = "m"\n')
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())
        _write(root / "publish" / "lane" / "other.ipynb", _notebook())
        seen: dict[str, dict] = {}

        def fake_execute(source, target, timeout, parameters):
            seen[source.stem] = parameters
            _write(target, _notebook(["ran\n"]))

        monkeypatch.setattr(engine, "execute", fake_execute)
        assert engine.main(["--parameters", '{"epochs": 3}'], root=root) == 0
        assert seen == {"nb": {"epochs": 3, "name": "m"}, "other": {"epochs": 3}}

    def test_a_parameter_key_naming_no_notebook_is_refused(self, tmp_path, capsys):
        """A typo would otherwise render the docs with the notebook's defaults and no error anywhere."""
        root = _repo(tmp_path, extra='[tool.nbpress.docs_parameters."lane/nbb"]\nepochs = 1\n')
        _write(root / "publish" / "lane" / "nb.ipynb", _notebook())
        assert engine.main(["--check-stale"], root=root) == 1
        assert "['lane/nbb']" in capsys.readouterr().err
