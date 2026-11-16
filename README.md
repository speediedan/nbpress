# nbpress

Publish tutorial notebooks from dev sources into Colab-ready copies and executed docs artifacts, with a staleness gate.

A repository using nbpress keeps each tutorial notebook in three lanes:

1. **dev**: the copies authors edit.
2. **publish**: the copies users clone and run. nbpress drops `remove-cell` tagged cells, rewrites dev-path imports,
   and prepends a Colab badge and an install cell. Outputs are kept stripped.
3. **docs artifacts**: the published notebooks, executed, with their outputs. A docs site renders these in preference to
   the published copies, so the docs show real output from notebooks the docs host cannot run itself (a GPU, gated
   weights, tokens).

The staleness gate (`nbpress-render --check-stale`) fails, naming each notebook, when an artifact is missing, no
longer matches its published source, shows a section that skipped at render time, or names a path into a checkout of
the repository (the renderer writes those repository-relative, since a working-copy location means nothing to a reader).
Each of these leaves a docs page showing something stale or host-specific, with no error in the docs build.

Other tools cover parts of this: nbstripout (stripping), papermill and nbconvert (execution), jupytext (pairing),
nbsphinx, myst-nb and jupyter-book (rendering). nbpress adds the contract between the three lanes and the check that
holds them together.

## Install

nbpress is consumed as a git-pinned dev dependency, not from PyPI:

```bash
pip install "nbpress @ git+https://github.com/speediedan/nbpress@v0.1.0"
# with papermill, to execute notebooks into docs artifacts
pip install "nbpress[render] @ git+https://github.com/speediedan/nbpress@v0.1.0"
```

The publisher, the stripper and the stale check need only the standard library (Python 3.11 or newer), so they run in
pre-commit and in a docs job before any project dependency is installed. Only executing notebooks needs papermill.

## Configuration

Everything repository-specific lives in the `[tool.nbpress]` table of the consuming repository's `pyproject.toml`.
Paths are relative to the directory holding it.

```toml
[tool.nbpress]
dev_dir = "examples/dev"                  # required
publish_dir = "examples/publish"          # required
colab_repo = "org/repo"                   # required: the GitHub repository the Colab badge opens
install_cell = ["# %pip install my-package[examples]"]   # required: lines of the prepended install cell
colab_branch = "main"                     # optional
hash_key_base = ""                        # optional: the directory stored hash keys are relative to
docs_artifact_dir = "docs/notebook_artifacts"   # required by nbpress-render
docs_hooks = "scripts/notebook_docs_hooks.py"   # optional repository hooks, loaded by file path
docs_render_command = "nbpress-render"    # optional: the command drift reports tell you to run

[tool.nbpress.import_rewrites]            # optional substring rewrites applied to code cells
"examples.dev." = "examples.publish."

[tool.nbpress.docs_parameters."lane/notebook"]   # optional papermill parameters, keyed by path under publish_dir
epochs = 1
```

A key no nbpress tool reads is refused by name, so a misspelled key fails instead of falling back to a default. The
table's earlier names, `[tool.notebook-publishing]` and `[tool.interpretune.notebooks]`, are still read; a
`pyproject.toml` carrying more than one of them is refused rather than merged.

## Commands

| command | what it does |
| --- | --- |
| `nbpress-publish [--check-only] [--force] [--dry-run]` | publish the dev files whose content hash changed; `--check-only` exits 1 when any is out of date |
| `nbpress-render --notebook NAME` | execute published notebooks into docs artifacts (needs the `render` extra and the notebook's own environment) |
| `nbpress-render --no-execute` | refresh artifacts without executing, keeping existing outputs |
| `nbpress-render --check-stale` | the staleness gate: exit 3 on drift, so a caller can tell drift from a crash (exit 1) or a usage error (exit 2) |
| `nbpress-render --list` | each artifact's state: missing, without outputs, or executed |
| `nbpress-render --restamp` | rewrite the repository hook's stamp without executing (needs a `restamp` hook) |
| `nbpress-strip NOTEBOOK...` | clear outputs and volatile metadata, keeping cell tags |

Each command finds the repository root as the nearest directory holding a `pyproject.toml`; `--root` overrides it.

## pre-commit

```yaml
- repo: https://github.com/speediedan/nbpress
  rev: v0.1.0
  hooks:
    - id: nbpress-strip
      exclude: ^docs/notebook_artifacts/      # executed on purpose: their outputs are the content
    - id: nbpress-publish
      files: ^examples/dev/.*\.ipynb$
```

`nbpress-check-stale` is also available as a hook. If your `docs_hooks` file imports anything beyond the standard
library, run the check from your own environment instead, since pre-commit installs nbpress in isolation.

## Repository hooks

`docs_hooks` names a Python file defining `HOOKS`, a dict of any of these callables (an unknown name is refused):

- `stamp(notebook)`: add repository metadata to an artifact on every write.
- `check(artifact, *, rel, output_text) -> [(kind, message), ...]`: extra `--check-stale` checks over an artifact
  whose sources match; `kind` is `"drift"` (fails the check) or `"note"` (reported only).
- `notes() -> [message, ...]`: notes reported once per `--check-stale` run.
- `restamp(artifact, *, output_text) -> (outcome, detail)`: rewrite the stamp without executing, for `--restamp`;
  `outcome` is `"unchanged"`, `"restamped"` or `"refused"`.

## License

Apache-2.0
