"""Exercise cache contracts with installed scripts and downstream caller workflows."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

from tauceti_tools.project import load
from tauceti_tools.scaffold import initial_configuration
from tauceti_tools.templates import materialize, write_project

FIXTURE = tempfile.TemporaryDirectory(prefix="installed-cache-contracts-")
project = Path(FIXTURE.name)
config = project / "tauceti.toml"
config.write_text(initial_configuration("yuma-mizuno-lean/Mei", "human"))
configuration = load(str(config))
write_project(configuration, project)
materialize(configuration, project / "scripts")
(project / "lean-toolchain").write_text("leanprover/lean4:v4.36.0-rc1\n")
sys.path.insert(0, str(project / "scripts"))
contracts = []
for name in ("reuse", "publish"):
    spec = importlib.util.spec_from_file_location(
        "installed_cache_" + name, project / f"scripts/test_lake_cache_{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    contracts.append(module)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite([
        loader.loadTestsFromTestCase(contracts[0].ReuseTests),
        loader.loadTestsFromTestCase(contracts[1].PublicationTests),
    ])
