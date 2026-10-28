#!/usr/bin/env python3
"""Bound the existing official elan installation and retry transient transport failures.

Keep the exact release pin, TLS verification, and elan's official download path.
No alternate installer, cache writer, mirror, credentials, or provenance manifest
is introduced. Non-transport failures are returned immediately.
"""

import argparse
import re
import subprocess
import time


ATTEMPT_SECONDS = 180
BACKOFF_SECONDS = (5, 15)
TRANSIENT = re.compile(
    r"SSL connect error|TLS connect error|connection reset|connection timed out|"
    r"Timeout was reached|Could not resolve host|Couldn't connect to server",
    re.IGNORECASE,
)


def output_text(output):
    return output.decode(errors="replace") if isinstance(output, bytes) else (output or "")


def install(pin):
    if not re.fullmatch(r"leanprover/lean4:v[0-9][A-Za-z0-9.\-]*", pin):
        raise ValueError("expected an exact official Lean release pin")
    for attempt in range(len(BACKOFF_SECONDS) + 1):
        print(f"Official elan install attempt {attempt + 1}/3 (limit {ATTEMPT_SECONDS}s)", flush=True)
        try:
            result = subprocess.run(
                ["elan", "toolchain", "install", pin], check=False,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=ATTEMPT_SECONDS,
            )
            output, status = result.stdout, result.returncode
            retryable = bool(TRANSIENT.search(output))
        except subprocess.TimeoutExpired as error:
            output, status, retryable = output_text(error.output), 124, True
            print("::warning::official elan installation exceeded its time limit", flush=True)
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
        if status == 0 or not retryable or attempt == len(BACKOFF_SECONDS):
            return status
        delay = BACKOFF_SECONDS[attempt]
        print(f"::notice::transient official Lean download failure; retrying in {delay}s", flush=True)
        time.sleep(delay)
    raise AssertionError("unreachable")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pin")
    args = parser.parse_args()
    raise SystemExit(install(args.pin))


if __name__ == "__main__":
    main()
