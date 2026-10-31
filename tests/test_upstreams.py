"""The guard resolves trusted inputs and rejects candidate-controlled policy changes."""

import copy
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tauceti_tools.project import ConfigError, load
from tauceti_tools.scaffold import initial_configuration
from tauceti_tools.templates import ASSETS, render
from tauceti_tools.upstreams import guard, release, toolchain_for, update

PIN = "leanprover/lean4:v4.36.0-rc1"


class UpstreamTests(unittest.TestCase):
    def test_rendered_bump_guard_routes_downstream_and_preserves_canonical_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "tauceti.toml"
            config.write_text(initial_configuration("yuma-mizuno-lean/Mei", "human"))
            script = root / "check-bump.sh"
            script.write_text(render((ASSETS / "scripts/check-bump.sh").read_text(), load(str(config))))
            base, candidate = root / "base", root / "candidate"
            for checkout in (base, candidate):
                checkout.mkdir()
                (checkout / "lakefile.toml").write_text('name = "Mei"\n')
                (checkout / "lean-toolchain").write_text(PIN + "\n")
                (checkout / "lake-manifest.json").write_text('{"packages": []}\n')
            # Only formatting changes: enough to exercise dispatch before validation.
            (candidate / "lake-manifest.json").write_text('{"packages": []}\n\n')
            stub = root / "python3"
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 73\n')
            stub.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       TAUCETI_REPO="yuma-mizuno-lean/Mei", TAUCETI_CONF_SNAPSHOT=str(config))

            def run(**overrides):
                return subprocess.run(["bash", str(script), str(base), str(base), str(candidate)],
                                      env=dict(env, **overrides), capture_output=True, text=True)

            result = run()
            self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["-m", "tauceti_tools", "upstreams", "guard",
                             "--conf", str(config), "--base", str(base), "--merge-base", str(base),
                             "--checkout", str(candidate)])
            for overrides in ({"TAUCETI_REPO": "TauCetiProject/TauCeti"},
                              {"TAUCETI_REPO": ""}, {"TAUCETI_CONF_SNAPSHOT": ""}):
                result = run(**overrides)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertNotIn("upstreams", result.stdout)
            (candidate / "lake-manifest.json").write_bytes((base / "lake-manifest.json").read_bytes())
            result = run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("no lakefile or Lake-pin change", result.stdout)
            (candidate / "lakefile.toml").write_text('name = "ChangedPolicy"\n')
            result = run()
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("human-owned", result.stdout)
            self.assertNotIn("upstreams", result.stdout)

    def test_guard_reproduces_pins_from_base_and_rejects_tampering(self):
        direct = {"name": "cslib", "url": "https://github.com/leanprover/cslib", "type": "git",
                  "rev": "a" * 40, "inputRev": "main", "inherited": False}
        shared = {"name": "mathlib", "url": "https://github.com/leanprover-community/mathlib4",
                  "type": "git", "rev": "b" * 40, "inherited": True}
        before = {"packages": [direct, shared], "name": "Project"}
        expected = {"packages": [dict(direct, rev="c" * 40), dict(shared, rev="d" * 40)], "name": "Project"}
        project = SimpleNamespace(raw={"upstreams": [{"package": "cslib", "repo": "leanprover/cslib",
                                                     "branch": "main", "update": True}]})
        with tempfile.TemporaryDirectory() as tmp:
            base, candidate = (Path(tmp) / name for name in ("base", "candidate"))
            for root in (base, candidate):
                root.mkdir()
                (root / "lakefile.toml").write_text('name = "Project"\n')
                (root / "lean-toolchain").write_text(PIN + "\n")
            (base / "lake-manifest.json").write_text(json.dumps(before))
            (candidate / "lake-manifest.json").write_text(json.dumps(expected))
            with patch("tauceti_tools.upstreams.api", return_value={"status": "ahead"}), \
                    patch("tauceti_tools.upstreams.toolchain_for", return_value=PIN), \
                    patch("tauceti_tools.upstreams.resolve", return_value=expected) as resolver, \
                    redirect_stdout(io.StringIO()):
                guard(project, base, base, candidate)
                resolver.assert_called_once_with(base, [dict(direct, rev="c" * 40)], PIN)
                reordered = dict(expected, packages=list(reversed(expected["packages"])))
                (candidate / "lake-manifest.json").write_text(json.dumps(reordered))
                guard(project, base, base, candidate)
                for key, value in (("rev", "e" * 40), ("url", "https://github.com/attacker/fork"),
                                   ("configFile", "payload.lean")):
                    tampered = copy.deepcopy(expected)
                    tampered["packages"][1][key] = value
                    (candidate / "lake-manifest.json").write_text(json.dumps(tampered))
                    with self.assertRaisesRegex(ConfigError, "differs from Lake"):
                        guard(project, base, base, candidate)
                (candidate / "lake-manifest.json").write_text(json.dumps(expected))
                resolver.reset_mock()
                project.raw["upstreams"][0]["update"] = False
                with self.assertRaisesRegex(ConfigError, "not configured"):
                    guard(project, base, base, candidate)
                resolver.assert_not_called()
                (candidate / "lakefile.toml").write_text('name = "ChangedPolicy"\n')
                with self.assertRaisesRegex(ConfigError, "human-owned"):
                    guard(project, base, base, candidate)
                resolver.assert_not_called()
                # A source-only PR behind a base pin update still passes without resolution.
                guard(project, candidate, base, base)

    def test_failed_resolution_preserves_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lakefile.toml").write_text('name = "Project"\n')
            (root / "lean-toolchain").write_text(PIN + "\n")
            (root / "lake-manifest.json").write_text('{"packages": []}\n')
            for args in (("init", "-q"), ("add", "."),
                         ("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Fixture")):
                subprocess.run(["git", "-C", str(root), *args], check=True)
            original = {name: (root / name).read_bytes() for name in ("lake-manifest.json", "lean-toolchain")}
            with patch("tauceti_tools.upstreams.inspect", return_value=([{"package": "cslib", "new": "c" * 40}], PIN)), \
                    patch("tauceti_tools.upstreams.resolve", side_effect=ConfigError("Lake failure")), \
                    redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ConfigError, "Lake failure"):
                    update(None, root, apply=True)
            self.assertEqual(original, {name: (root / name).read_bytes() for name in original})

    def test_newest_official_toolchain_without_requiring_equality_or_downgrading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lean-toolchain").write_text(PIN)
            rows = [{"name": "cslib", "url": "https://github.com/leanprover/cslib", "type": "git", "rev": "a" * 40},
                    {"name": "TauCeti", "url": "https://github.com/TauCetiProject/TauCeti", "type": "git", "rev": "b" * 40}]
            with patch("tauceti_tools.upstreams.file_at", side_effect=["leanprover/lean4:v4.35.0", PIN]):
                self.assertEqual(toolchain_for(root, rows), PIN)
        self.assertLess(release(PIN), release("leanprover/lean4:v4.36.0"))
        with self.assertRaises(ConfigError):
            release("attacker/lean:v4.36.0")

    def test_updater_and_guard_install_the_same_pinned_runtime(self):
        root = Path(__file__).resolve().parents[1]
        pins = re.compile(r"^\s*((?:BWRAP|ELAN)_[A-Z0-9_]+):\s*(\S+)\s*$", re.MULTILINE)
        shared = dict(pins.findall((root / ".github/workflows/pr-build.yml").read_text()))
        updater = dict(pins.findall((root / "tauceti_tools/assets/project/.github/workflows/update-upstreams.yml").read_text()))
        self.assertEqual(len(shared), 5)
        self.assertEqual(updater, shared)


if __name__ == "__main__":
    unittest.main()
