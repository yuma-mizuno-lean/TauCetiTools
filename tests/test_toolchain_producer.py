"""Check downstream snapshot supply and its repository/main trust boundary."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

from tauceti_tools.project import load
from tauceti_tools.scaffold import initial_configuration
from tauceti_tools.templates import materialize, write_project


class DownstreamToolchainProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / "config.toml"
        config.write_text(initial_configuration("one/Project", "human") +
                          '\n[tools.tools]\nrepo="TauCetiProject/TauCetiTools"\nref="' + "a" * 40 +
                          '"\n[tools.review]\nrepo="TauCetiProject/TauCetiReview"\nref="' + "b" * 40 + '"\n')
        self.project = load(str(config))
        self.checkout = self.root / "project"
        self.checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(self.checkout)], check=True)
        write_project(self.project, self.checkout)

    def test_generated_project_has_a_main_only_key_free_producer(self):
        path = self.checkout / ".github/workflows/warm-dependencies.yml"
        workflow = yaml.safe_load(path.read_text())
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(triggers["push"]["branches"], ["main"])
        self.assertIn("workflow_dispatch", triggers)
        self.assertNotIn("pull_request", triggers)
        self.assertNotIn("pull_request_target", triggers)
        job = workflow["jobs"]["warm"]
        self.assertEqual(job["if"], "github.ref == 'refs/heads/main'")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        encoded = json.dumps(workflow)
        self.assertNotIn("secrets.", encoded)
        self.assertNotIn("lake build", encoded)
        self.assertNotIn("__TOOLS_", encoded)
        checkout = job["steps"][0]
        self.assertEqual(checkout["with"]["ref"], "${{ github.workflow_sha }}")
        self.assertFalse(checkout["with"]["persist-credentials"])
        steps = job["steps"]
        seal = next(i for i, s in enumerate(steps) if "Seal official files" in s.get("name", ""))
        save = next(i for i, s in enumerate(steps) if "cache/save@" in s.get("uses", ""))
        self.assertLess(seal, save)
        self.assertEqual(steps[save]["with"]["key"], "${{ steps.toolchain.outputs.key }}")
        consumer = (self.checkout / ".github/actions/restore-lean-toolchain/action.yml").read_text()
        self.assertNotIn("cache/save", consumer)
        self.assertNotIn("restore-keys", consumer)
        self.assertTrue((self.checkout / ".github/actions/restore-lean-toolchain/install_official_lean.py").is_file())

    def test_materialized_snapshot_is_bound_to_the_downstream_repository(self):
        scripts = self.root / "scripts"
        materialize(self.project, scripts)
        spec = importlib.util.spec_from_file_location("downstream_snapshot", scripts / "toolchain_snapshot.py")
        snapshot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(snapshot)
        release = self.root / "release"
        (release / "bin").mkdir(parents=True)
        for name in ("lean", "lake"):
            binary = release / "bin" / name
            binary.write_text("#!/bin/sh\nexit 0\n")
            binary.chmod(0o755)
        pin = "leanprover/lean4:v4.36.0-rc1"
        snapshot.seal(release, pin, "a" * 40, "123")
        snapshot.verify(release, pin)
        manifest = release / snapshot.MANIFEST
        data = json.loads(manifest.read_text())
        self.assertEqual(data["producer"], "one/Project/.github/workflows/warm-dependencies.yml")
        for producer in ("TauCetiProject/TauCeti/.github/workflows/warm-dependencies.yml",
                         "other/Project/.github/workflows/warm-dependencies.yml"):
            with self.subTest(producer=producer):
                manifest.write_text(json.dumps({**data, "producer": producer}))
                with self.assertRaises(ValueError):
                    snapshot.verify(release, pin)


if __name__ == "__main__":
    unittest.main()
