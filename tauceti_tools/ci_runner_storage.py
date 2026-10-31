"""Reclaim unused image SDKs before expanding Lean caches on hosted Linux runners.

Only fixed SDK directories are eligible. Project checkouts, caches and runner
diagnostics are never cleanup targets; self-hosted machines are never modified.
"""

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


SDK_DIRECTORIES = (Path('/usr/local/lib/android'), Path('/usr/share/dotnet'))


def reclaim():
    if os.environ.get('TAUCETI_RUNNER_ENVIRONMENT') != 'github-hosted' or platform.system() != 'Linux':
        return []
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
    before = shutil.disk_usage(workspace).free
    targets = []
    # Validate the entire allowlist before deleting any directory.
    for directory in SDK_DIRECTORIES:
        if directory.is_symlink():
            raise RuntimeError(f'Refusing symlinked SDK directory: {directory}')
        if not directory.exists():
            continue
        resolved = directory.resolve(strict=True)
        if resolved != directory:
            raise RuntimeError(f'Refusing redirected SDK directory: {directory}')
        if resolved == workspace or resolved in workspace.parents or workspace in resolved.parents:
            raise RuntimeError(f'SDK cleanup overlaps the workspace: {resolved}')
        targets.append(resolved)
    for target in targets:
        subprocess.run(['sudo', '-n', 'rm', '-rf', '--', str(target)], check=True)
    print(json.dumps({'schema': 'tauceti-ci.runner-storage/v1',
                      'removed_sdk_directories': [str(p) for p in targets],
                      'free_bytes_before': before,
                      'free_bytes_after': shutil.disk_usage(workspace).free}))
    return targets


if __name__ == '__main__':
    reclaim()
