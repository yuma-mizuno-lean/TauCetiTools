# Tau Ceti Tools

Shared configuration, CI and administration for Lean projects using the Tau Ceti workflow.
This repository is independent of the example [worker harness](https://github.com/TauCetiProject/TauCetiWorker).
[Review](https://github.com/TauCetiProject/TauCetiReview),
[Progress](https://github.com/TauCetiProject/TauCetiProgress) and
[Bors](https://github.com/TauCetiProject/bors-ng) remain separate implementations.

**[Architecture and manual setup](docs/project-setup.md)** documents the installation from scratch,
including repositories, ownership, workflows, Apps, credentials, merge rules and optional services.
It does not require doctor.

```sh
uv tool install git+https://github.com/TauCetiProject/TauCetiTools
tauceti-tools doctor
tauceti-tools init --repo YOUR_ORG/YOUR_PROJECT --owner-login YOUR_LOGIN
tauceti-tools doctor
tauceti-tools doctor --no-extras
```

Select immutable tool versions in the generated configuration before installing workflows.
Doctor reads by default. `--fix CHECK_ID` previews a repair; adding `--apply` performs it.
Credential presence and successful use are reported separately.
Optional extras are included by default, after the core checks; `--no-extras` omits them.
Disabled extras are reported as disabled and do not need setting up.
The human report summarizes successful checks and prints the full repair procedure for
each outstanding item, including service-operator work. `--check CHECK_ID` selects one
check; it does not change the instructions. `--json` includes each check's result and repair instructions.
Missing, empty and invalid configuration files produce starter-generation and repair commands.
`init` fills a missing or empty file, preserves a nonempty file, and defaults to GitHub's
merge queue. Bors is the other supported merger. Administrators override scope blocks with
an admin merge when using the queue, or with `bors merge` when using Bors.
Doctor checks the merge settings directly rather than scanning PRs.

App-dependent workflows skip with a setup message while credentials are missing; builds still
run. Doctor separately reports missing settings, observed credential failures and successful
use that has not been checked yet. A successful rerun can verify credentials even when the
original workflow run predates the credential update.

Generated projects include `warm-dependencies.yml`, a main-only producer of verified official
Lean snapshots. GitHub Actions caches are scoped to a repository: a downstream project cannot
restore Tau Ceti's snapshot merely because both projects use the same Lean pin. After first
installing these workflows on main, run `gh workflow run warm-dependencies.yml --ref main`
in the downstream repository. Later main changes to the release pin or warmer trigger it again.
The producer runs no project compilation and receives no publication credentials. PR builds
only restore and verify the exact-pin snapshot; they never publish it. A missing snapshot uses
the same official elan installation, with bounded retries for transient TLS failures and a
per-attempt timeout. Permanent installer failures are returned immediately.

Configuration is selected in this order: explicit `--conf PATH_OR_HTTPS_URL`,
`TAUCETI_CONF`, `tauceti.toml` in the current directory, then `tauceti.toml` at the
current Git checkout's root. This works from subdirectories and Git worktrees too.
Without any project configuration, `tauceti doctor` checks the worker host.

Worker and engine commands use the same `--conf PATH_OR_HTTPS_URL`. A worker keeps a local
configuration snapshot for its process tree and adopts online edits only on restart or explicit refresh.
Project data and local worker identities are isolated; provider quotas remain account-wide.

Optional Bors `hosted` mode supplies a separate operator-funded Neon project. The downstream
still operates Bors, on its own Docker host or Cloudflare account. Hosted state-service access
requires a separate operator grant.

A [disposable project](examples/disposable-project) supplies separate content and roadmap trees
with real immutable tool and Mathlib pins. It does not create repositories or enroll hosted services.
