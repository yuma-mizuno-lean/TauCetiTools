"""Exercise the actual composite-action helper without network or a Lean download."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml


HELPER = (Path(__file__).resolve().parents[1] / "tauceti_tools/assets/project/.github/actions/"
          "restore-lean-toolchain/install_official_lean.py")
spec = importlib.util.spec_from_file_location("official_lean_install", HELPER)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
PIN = "leanprover/lean4:v4.36.0-rc1"


class OfficialLeanInstallTests(unittest.TestCase):
    def invoke(self, outcomes):
        with patch.object(installer.subprocess, "run", side_effect=outcomes) as run, \
                patch.object(installer.time, "sleep") as sleep:
            status = installer.install(PIN)
        for call in run.call_args_list:
            self.assertEqual(call.args[0], ["elan", "toolchain", "install", PIN])
            self.assertEqual(call.kwargs["timeout"], 180)
        return status, run, sleep

    def test_success_needs_no_retry(self):
        status, run, sleep = self.invoke([subprocess.CompletedProcess([], 0, "installed\n")])
        self.assertEqual(status, 0)
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_tls_failure_then_success_reuses_exact_official_pin(self):
        status, run, sleep = self.invoke([
            subprocess.CompletedProcess([], 1, "error: [35] SSL connect error\n"),
            subprocess.CompletedProcess([], 0, "installed\n"),
        ])
        self.assertEqual(status, 0)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_persistent_transport_failure_is_finite(self):
        status, run, sleep = self.invoke([
            subprocess.CompletedProcess([], 1, "TLS connect error") for _ in range(3)
        ])
        self.assertEqual(status, 1)
        self.assertEqual(run.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 15])

    def test_hung_download_is_bounded_then_retried(self):
        status, run, sleep = self.invoke([
            subprocess.TimeoutExpired(["elan"], 180, output=b"downloading\n"),
            subprocess.CompletedProcess([], 0, "installed\n"),
        ])
        self.assertEqual(status, 0)
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_persistent_timeout_has_failure_status(self):
        status, run, _ = self.invoke([subprocess.TimeoutExpired(["elan"], 180)] * 3)
        self.assertEqual(status, 124)
        self.assertEqual(run.call_count, 3)

    def test_permanent_failure_is_not_retried(self):
        for message in ("HTTP 404: no such release", "unsupported archive", "permission denied"):
            with self.subTest(message=message):
                status, run, sleep = self.invoke([subprocess.CompletedProcess([], 7, message)])
                self.assertEqual(status, 7)
                self.assertEqual(run.call_count, 1)
                sleep.assert_not_called()

    def test_untrusted_or_floating_pin_is_rejected_before_execution(self):
        with patch.object(installer.subprocess, "run") as run:
            for pin in ("nightly", "fork/lean4:v4.36.0-rc1", "leanprover/lean4:main", "../lean"):
                with self.subTest(pin=pin), self.assertRaises(ValueError):
                    installer.install(pin)
            run.assert_not_called()


class CompositeActionTests(unittest.TestCase):
    def invoke(self, *, warm=False, failure=False):
        action = yaml.safe_load(HELPER.with_name("action.yml").read_text())
        command = action["runs"]["steps"][-1]["run"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binaries = root / ".elan/bin"
            binaries.mkdir(parents=True)
            tooling = root / "tooling/scripts"
            tooling.mkdir(parents=True)
            # Exercise the action's actual warm/cold branching; validation's
            # provenance and digest behavior has separate snapshot tests.
            (tooling / "toolchain_snapshot.py").write_text("raise SystemExit(" + str(0 if warm else 1) + ")\n")
            (root / "lean-toolchain").write_text(PIN + "\n")
            (binaries / "elan").write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/install-log"\n'
                + ("echo 'HTTP 404: no such release'; exit 7\n" if failure else "exit 0\n"))
            (binaries / "lean").write_text(
                '#!/bin/sh\nprintf "%s\\n" "$ELAN_TOOLCHAIN" > "$HOME/version-pin"\n')
            for binary in binaries.iterdir():
                binary.chmod(0o755)
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", command],
                                    capture_output=True, text=True, env={
                                        **os.environ, "HOME": str(root), "PROJECT": str(root),
                                        "TOOLING": str(root / "tooling"), "SNAPSHOT": str(root / "snapshot"),
                                        "GITHUB_ACTION_PATH": str(HELPER.parent),
                                    })
            installs = (root / "install-log").read_text() if (root / "install-log").exists() else ""
            version_pin = (root / "version-pin").read_text() if (root / "version-pin").exists() else None
            return result, installs, version_pin

    def test_warm_snapshot_still_skips_installation(self):
        result, installs, version_pin = self.invoke(warm=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(installs, "")
        self.assertEqual(version_pin, PIN + "\n")

    def test_cold_action_executes_helper_and_checks_exact_toolchain(self):
        result, installs, version_pin = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(installs, "toolchain install " + PIN + "\n")
        self.assertEqual(version_pin, PIN + "\n")

    def test_permanent_installer_failure_blocks_the_action(self):
        result, installs, version_pin = self.invoke(failure=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(installs, "toolchain install " + PIN + "\n")
        self.assertIsNone(version_pin)


if __name__ == "__main__":
    unittest.main()
