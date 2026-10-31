import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tauceti_tools import ci_runner_storage as storage


class RunnerStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.sdk = self.root / 'sdk'
        self.sdk.mkdir()
        for context in [patch.dict(os.environ, {'TAUCETI_RUNNER_ENVIRONMENT': 'github-hosted',
                                              'GITHUB_WORKSPACE': str(self.workspace)}),
                        patch.object(storage.platform, 'system', return_value='Linux'),
                        patch.object(storage, 'SDK_DIRECTORIES', (self.sdk,))]:
            context.start()
            self.addCleanup(context.stop)

    @patch.object(storage.subprocess, 'run')
    def test_only_fixed_sdk_paths_are_removed(self, run):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(storage.reclaim(), [self.sdk])
        run.assert_called_once_with(['sudo', '-n', 'rm', '-rf', '--', str(self.sdk)], check=True)
        self.assertIn('free_bytes_after', output.getvalue())
        self.assertTrue(self.workspace.is_dir())

    @patch.object(storage.subprocess, 'run')
    def test_self_hosted_runner_is_untouched(self, run):
        with patch.dict(os.environ, {'TAUCETI_RUNNER_ENVIRONMENT': 'self-hosted'}):
            self.assertEqual(storage.reclaim(), [])
        run.assert_not_called()

    @patch.object(storage.subprocess, 'run')
    def test_non_linux_runner_is_untouched(self, run):
        with patch.object(storage.platform, 'system', return_value='Windows'):
            self.assertEqual(storage.reclaim(), [])
        run.assert_not_called()

    @patch.object(storage.subprocess, 'run')
    def test_workspace_overlap_is_rejected(self, run):
        for target in [self.workspace, self.root, self.workspace / 'child']:
            target.mkdir(exist_ok=True)
            with self.subTest(target=target), patch.object(storage, 'SDK_DIRECTORIES', (target,)):
                with self.assertRaisesRegex(RuntimeError, 'overlaps'):
                    storage.reclaim()
        run.assert_not_called()

    @patch.object(storage.subprocess, 'run')
    def test_all_paths_validated_before_any_removal(self, run):
        redirected = self.root / 'redirected'
        redirected.symlink_to(self.workspace, target_is_directory=True)
        with patch.object(storage, 'SDK_DIRECTORIES', (self.sdk, redirected)):
            with self.assertRaisesRegex(RuntimeError, 'symlinked'):
                storage.reclaim()
        run.assert_not_called()

    @patch.object(storage.subprocess, 'run')
    def test_missing_sdk_is_harmless(self, run):
        with patch.object(storage, 'SDK_DIRECTORIES', (self.root / 'missing',)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(storage.reclaim(), [])
        run.assert_not_called()

    @patch.object(storage.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'sudo'))
    def test_failed_cleanup_is_not_reported_as_success(self, run):
        with self.assertRaises(subprocess.CalledProcessError):
            storage.reclaim()


if __name__ == '__main__':
    unittest.main()
