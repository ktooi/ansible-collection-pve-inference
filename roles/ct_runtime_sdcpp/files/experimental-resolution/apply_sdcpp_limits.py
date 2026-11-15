#!/usr/bin/env python3
"""Apply the pinned sd.cpp resolution patch after exact content checks.

Use --check for a read-only preflight. JSON on stdout reports the state.
The source may be an isolated Git checkout or an exported source copy.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

REVISION = "32d516c0197ed5ca31305b8575e14eb1451fad33"
FILES = {
    "examples/server/runtime.h",
    "examples/server/runtime.cpp",
    "examples/server/routes_sdcpp.cpp",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_git(source, *args):
    completed = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(source), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {args[0]} failed: {detail}")
    return completed.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--check", action="store_true", help="Check without changing files")
    args = parser.parse_args()
    source = args.source_dir.resolve(strict=True)
    if not source.is_dir():
        raise RuntimeError("--source-dir must identify a source directory")
    if not shutil.which("git"):
        raise RuntimeError("git is required to validate and apply this patch")

    bundle = Path(__file__).resolve().parent
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("upstream_revision") != REVISION:
        raise RuntimeError("Unsupported patch manifest or upstream revision")
    records = manifest.get("files", [])
    if len(records) != len(FILES) or {item.get("path") for item in records} != FILES:
        raise RuntimeError("The manifest does not identify the expected three source files")
    if manifest.get("patch_file") != "sdcpp-resolution.patch":
        raise RuntimeError("Unexpected patch filename")
    patch = bundle / "sdcpp-resolution.patch"
    if digest(patch) != manifest.get("patch_sha256"):
        raise RuntimeError("The patch SHA-256 does not match manifest.json")

    git_revision_verified = False
    if (source / ".git").exists():
        top = Path(run_git(source, "rev-parse", "--show-toplevel")).resolve()
        if top != source:
            raise RuntimeError("--source-dir must be the checkout root")
        current_revision = run_git(source, "rev-parse", "--verify", "HEAD")
        if current_revision != REVISION:
            raise RuntimeError(f"Source HEAD must be {REVISION}; found {current_revision}")
        git_revision_verified = True

    states = []
    for record in records:
        path = source / record["path"]
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(source):
            raise RuntimeError(f"Missing or unsafe source file: {record['path']}")
        actual = digest(path)
        if actual == record["before_sha256"]:
            states.append("pristine")
        elif actual == record["after_sha256"]:
            states.append("patched")
        else:
            raise RuntimeError(f"Unrecognized source content: {record['path']}; refusing to overwrite")
    if len(set(states)) != 1:
        raise RuntimeError("Mixed pristine/patched files; refusing a partial or ambiguous patch state")

    result = {
        "source_dir": str(source),
        "source_revision": REVISION,
        "git_revision_verified": git_revision_verified,
        "patch_sha256": manifest["patch_sha256"],
        "changed": False,
        "would_change": False,
        "check_mode": args.check,
    }
    if states[0] == "patched":
        result["state"] = "already_applied"
        print(json.dumps(result, sort_keys=True))
        return 0

    run_git(source, "apply", "--check", "--whitespace=error-all", str(patch))
    if args.check:
        result.update(state="pristine", would_change=True)
        print(json.dumps(result, sort_keys=True))
        return 0

    run_git(source, "apply", "--whitespace=error-all", str(patch))
    for record in records:
        if digest(source / record["path"]) != record["after_sha256"]:
            raise RuntimeError(f"Post-apply verification failed: {record['path']}; inspect the isolated source copy")
    result.update(state="applied", changed=True)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        sys.exit(2)
