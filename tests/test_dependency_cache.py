import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tauceti_tools.project import parse
from tauceti_tools.templates import materialize


class DependencyCacheTests(unittest.TestCase):
    def test_rendered_policy_fetches_exact_pin_and_rejects_other_repository(self):
        # Self-contained policy: the candidate tree never supplies endpoints.
        data = b'''schema_version=1
[project]
name="Example"
[repositories]
content="example/Example"
roadmap="example/Roadmap"
[lean]
roots=["Example"]
[[upstreams]]
repo="example/Dependency"
package="Dependency"
cache_artifact_url="https://cache.example.org/artifacts"
cache_revision_url="https://cache.example.org/revisions"
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            materialize(parse(data), root / "scripts")
            script = root / "scripts/lake_dependency_cache.py"
            spec = importlib.util.spec_from_file_location("dependency_fetch", script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            package = dict(name="Dependency", url="https://github.com/example/Dependency", rev="a" * 40)
            manifest = root / "lake-manifest.json"
            manifest.write_text(json.dumps(dict(packages=[package])))
            with patch.object(module.sys, "argv", [str(script), str(root)]), patch.object(module.subprocess, "run") as run:
                module.main()
                args = run.call_args.args[0]
                self.assertEqual(args[args.index("--rev") + 1], "a" * 40)
                self.assertIn("--max-revs=1", args)
                self.assertEqual(args[args.index("--package") + 1], "Dependency")
                run.reset_mock()
                package["url"] = "https://github.com/attacker/Dependency"
                manifest.write_text(json.dumps(dict(packages=[package])))
                with self.assertRaises(SystemExit):
                    module.main()
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
