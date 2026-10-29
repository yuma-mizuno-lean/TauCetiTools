import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from tauceti_tools.project import parse
from tauceti_tools.templates import materialize


class DependencyCacheTests(unittest.TestCase):
    def load_fetcher(self):
        script = Path(__file__).resolve().parents[1] / "tauceti_tools/assets/scripts/lake_dependency_cache.py"
        spec = importlib.util.spec_from_file_location("dependency_fetch", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_broken_pipe_retries_same_exact_command_then_succeeds(self):
        module = self.load_fetcher()
        command = ["lake", "cache", "get", "--rev", "a" * 40, "--max-revs=1"]
        failure = subprocess.CalledProcessError(1, command, output="error: curl exited with code 55\n")
        success = subprocess.CompletedProcess(command, 0, stdout="verified artifacts restored\n")
        with patch.object(module.subprocess, "run", side_effect=[failure, success]) as run, patch.object(module.time, "sleep") as sleep:
            module.fetch(command, Path("."), {"LAKE_CONFIG": "trusted-config"})
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args, run.call_args_list[1].args)
        self.assertEqual(run.call_args_list[0].kwargs["env"], run.call_args_list[1].kwargs["env"])
        sleep.assert_called_once_with(2)

    def test_repeated_transfer_failure_is_bounded_and_still_fails(self):
        module = self.load_fetcher()
        failure = subprocess.CalledProcessError(1, ["lake"], output="curl exited with code 55\n")
        with patch.object(module.subprocess, "run", side_effect=failure) as run, patch.object(module.time, "sleep") as sleep:
            with self.assertRaises(subprocess.CalledProcessError):
                module.fetch(["lake"], Path("."), {})
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4])

    def test_other_failures_are_not_retried(self):
        module = self.load_fetcher()
        for output in ("no outputs found", "HTTP 429 Retry-After: 900", "hash mismatch", "curl exited with code 22",
                       "curl exited with code 55\nHTTP 429 Retry-After: 900",
                       "curl exited with code 55\nhash mismatch"):
            with self.subTest(output=output):
                failure = subprocess.CalledProcessError(1, ["lake"], output=output)
                with patch.object(module.subprocess, "run", side_effect=failure) as run, patch.object(module.time, "sleep") as sleep:
                    with self.assertRaises(subprocess.CalledProcessError):
                        module.fetch(["lake"], Path("."), {})
                self.assertEqual(run.call_count, 1)
                sleep.assert_not_called()

    def test_fetch_does_not_extend_the_original_deadline(self):
        module = self.load_fetcher()
        failure = subprocess.CalledProcessError(1, ["lake"], output="curl exited with code 55\n")
        with patch.object(module.subprocess, "run", side_effect=failure) as run, \
             patch.object(module.time, "monotonic", side_effect=[100, 101, 699]), \
             patch.object(module.time, "sleep") as sleep:
            with self.assertRaises(subprocess.CalledProcessError):
                module.fetch(["lake"], Path("."), {})
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs["timeout"], 599)
        sleep.assert_not_called()

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
            with patch.object(module.sys, "argv", [str(script), str(root)]), patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout="")) as run:
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
