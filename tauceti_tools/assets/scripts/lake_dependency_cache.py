#!/usr/bin/env python3
"""Read explicitly configured dependency caches before the offline build.

DEPENDENCIES is populated from the trusted project configuration by materialize;
never read cache endpoints from the candidate PR's configuration.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

DEPENDENCIES = []


def fetch(command, root, env):
    """Retry incomplete transfers within the existing ten-minute fetch deadline.

    Lake verifies hashes and installs complete artifacts atomically. Repeating the
    exact pinned request retains those artifacts and fetches only missing ones.
    HTTP/auth failures, cache misses and integrity failures remain hard failures.
    """
    deadline = time.monotonic() + 600
    transient = {5, 6, 7, 18, 28, 35, 52, 55, 56, 92}
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, 600)
        try:
            result = subprocess.run(command, cwd=root, env=env, check=True, timeout=remaining,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if result.stdout:
                print(result.stdout, end="", flush=True)
            return
        except subprocess.CalledProcessError as error:
            output = error.output or ""
            print(output, end="", flush=True)
            codes = {int(code) for code in re.findall(r"curl exited with code (\d+)", output)}
            delay = 2 ** (attempt + 1)
            permanent = re.search(r"HTTP[^\n]*\b[45]\d\d\b|Retry-After|hash mismatch|no outputs found", output, re.I)
            if permanent or not codes or not codes <= transient or attempt == 2 or time.monotonic() + delay >= deadline:
                raise
            print("::notice::Incomplete dependency cache transfer; retrying the same pinned request", flush=True)
            time.sleep(delay)


def main():
    if not DEPENDENCIES:
        return
    root = Path(sys.argv[1]).resolve()
    manifest = json.loads((root / "lake-manifest.json").read_text())
    packages = {p["name"]: p for p in manifest["packages"]}
    with tempfile.TemporaryDirectory(prefix="dependency-cache-") as tmp:
        config = Path(tmp) / "lake.toml"
        for dep in DEPENDENCIES:
            package = packages.get(dep["package"])
            expected = "https://github.com/" + dep["repo"]
            if not package or package.get("url", "").removesuffix(".git") != expected:
                raise SystemExit("Dependency cache repository does not match the validated manifest")
            config.write_text(
                '[[cache.service]]\nname = "dependency-public"\nkind = "s3"\n'
                + "artifactEndpoint = " + json.dumps(dep["cache_artifact_url"]) + "\n"
                + "revisionEndpoint = " + json.dumps(dep["cache_revision_url"]) + "\n"
            )
            env = dict(os.environ, LAKE_CONFIG=str(config))
            print("Fetching dependency cache: " + dep["repo"] + " at " + package["rev"], flush=True)
            fetch([
                "lake", "cache", "get", "--service", "dependency-public",
                "--repo", dep["repo"], "--package", dep["package"],
                "--rev", package["rev"], "--max-revs=1",
            ], root, env)
    # A root-package miss need not disable successfully downloaded dependencies.
    if os.environ.get("GITHUB_ENV"):
        cache = Path(os.environ.get("LAKE_CACHE_DIR") or root / ".lake/cache").resolve()
        with open(os.environ["GITHUB_ENV"], "a") as output:
            output.write(f"LAKE_CACHE_DIR={cache}\nLAKE_ARTIFACT_CACHE=true\nLAKE_RESTORE_ARTIFACTS=true\n")


if __name__ == "__main__":
    main()
