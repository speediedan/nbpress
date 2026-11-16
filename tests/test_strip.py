"""The output stripper (``nbpress-strip``)."""

from __future__ import annotations

import json

from test_publish import _code, _notebook, _repo

from nbpress.publish import load_notebook
from nbpress.publish import main as publish
from nbpress.strip import main


def test_strips_outputs_and_volatile_metadata_and_reports_the_change(tmp_path, capsys):
    cell = _code("x = 1\n")
    cell["outputs"] = [{"output_type": "stream", "name": "stdout", "text": ["1\n"]}]
    cell["execution_count"] = 3
    cell["metadata"]["execution"] = {"iopub.status.busy": "2026-01-01"}
    nb = _notebook(cell)
    nb["metadata"]["widgets"] = {"state": {}}
    path = tmp_path / "nb.ipynb"
    path.write_text(json.dumps(nb))
    assert main([str(path)]) == 1
    assert "Stripped outputs from" in capsys.readouterr().out
    stripped = load_notebook(path)
    assert stripped["cells"][0]["outputs"] == [] and stripped["cells"][0]["execution_count"] is None
    assert "execution" not in stripped["cells"][0]["metadata"] and "widgets" not in stripped["metadata"]
    # a clean notebook is left alone, and the hook passes
    before = path.read_bytes()
    assert main([str(path)]) == 0
    assert path.read_bytes() == before


def test_publishing_and_stripping_keep_a_papermill_parameters_cell(tmp_path):
    """A ``parameters`` cell must survive both, so a test or smoke run can shrink a notebook by injecting values."""
    root = _repo(tmp_path)
    params = _code("model = 'tiny'\nepochs = 1\n", tags=["parameters"])
    params["outputs"] = [{"output_type": "stream", "name": "stdout", "text": ["x\n"]}]
    (root / "examples" / "dev" / "nested" / "demo.ipynb").write_text(json.dumps(_notebook(params)))
    assert publish(["--root", str(root)]) == 0
    published = root / "examples" / "publish" / "nested" / "demo.ipynb"
    cell = load_notebook(published)["cells"][2]
    assert cell["metadata"]["tags"] == ["parameters"]
    assert "".join(cell["source"]).rstrip("\n") == "model = 'tiny'\nepochs = 1"
    main([str(published)])
    stripped = load_notebook(published)["cells"][2]
    assert stripped["metadata"]["tags"] == ["parameters"] and stripped["source"] == cell["source"]
