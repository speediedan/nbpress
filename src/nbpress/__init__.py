"""Publish tutorial notebooks from dev sources into Colab-ready copies and executed docs artifacts, with a staleness
gate.

Three console scripts, all configured from the ``[tool.nbpress]`` table of the consuming repository's
``pyproject.toml``: ``nbpress-publish`` (:mod:`nbpress.publish`), ``nbpress-render`` (:mod:`nbpress.render`) and
``nbpress-strip`` (:mod:`nbpress.strip`).
"""

__version__ = "0.1.0"
