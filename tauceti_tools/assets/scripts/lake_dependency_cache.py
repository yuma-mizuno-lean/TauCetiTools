#!/usr/bin/env python3
"""Read explicitly configured dependency caches before the offline build.

DEPENDENCIES is populated from the trusted project configuration by materialize;
never read cache endpoints from the candidate PR's configuration.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

DEPENDENCIES = []


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
            subprocess.run([
                "lake", "cache", "get", "--service", "dependency-public",
                "--repo", dep["repo"], "--package", dep["package"],
                "--rev", package["rev"], "--max-revs=1",
            ], cwd=root, env=env, check=True, timeout=600)
    # A root-package miss need not disable successfully downloaded dependencies.
    if os.environ.get("GITHUB_ENV"):
        cache = Path(os.environ.get("LAKE_CACHE_DIR") or root / ".lake/cache").resolve()
        with open(os.environ["GITHUB_ENV"], "a") as output:
            output.write(f"LAKE_CACHE_DIR={cache}\nLAKE_ARTIFACT_CACHE=true\nLAKE_RESTORE_ARTIFACTS=true\n")


if __name__ == "__main__":
    main()
