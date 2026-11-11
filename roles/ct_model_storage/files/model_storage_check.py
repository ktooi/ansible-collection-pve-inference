#!/usr/bin/env python3
"""Fail before using an absent, substituted, or inaccessible model filesystem."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


class StorageError(Exception):
    """A model-storage precondition was not met."""


def validate_path(value):
    """Reject ambiguous paths and symlinks, including existing parent symlinks."""
    if (not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value)
            or value == "/" or os.path.normpath(value) != value
            or "." in value.split("/") or ".." in value.split("/")):
        raise StorageError("Paths must be canonical absolute non-root paths without traversal or special characters.")
    current = Path("/")
    for component in Path(value).parts[1:]:
        current /= component
        try:
            information = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(information.st_mode):
            raise StorageError("Symlinks are not allowed in model-storage paths: " + str(current))
    return value


def filesystem_for(path):
    """Ask util-linux which mounted filesystem currently backs this exact path."""
    result = subprocess.run(
        ["findmnt", "--json", "--first-only", "--target", path,
         "--output", "TARGET,FSTYPE"],
        capture_output=True, text=True, check=False)
    if result.returncode:
        raise StorageError("findmnt could not identify the filesystem for " + path)
    try:
        entries = json.loads(result.stdout)["filesystems"]
        if not isinstance(entries, list) or len(entries) != 1:
            raise ValueError("expected one effective filesystem")
        entry = entries[0]
        if (not isinstance(entry["target"], str) or not entry["target"].startswith("/")
                or not isinstance(entry["fstype"], str)):
            raise ValueError("missing filesystem fields")
    except (KeyError, TypeError, ValueError) as error:
        raise StorageError("findmnt returned an invalid filesystem description for " + path) from error
    return entry


def probe_access(path, access):
    """Probe with the caller's credentials; never change namespace ownership."""
    if not os.access(path, os.R_OK | os.X_OK, effective_ids=True):
        raise StorageError("The runtime account cannot read and traverse " + path)
    with os.scandir(path) as entries:
        next(entries, None)
    if access == "read":
        return
    original = renamed = None
    try:
        descriptor, original = tempfile.mkstemp(prefix=".pve-inference-storage-probe-", dir=path)
        renamed = original + ".renamed"
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(b"pve-inference model storage probe\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(original, renamed)
        os.unlink(renamed)
    finally:
        for candidate in (original, renamed):
            if candidate is not None:
                try:
                    os.unlink(candidate)
                except FileNotFoundError:
                    pass


def check_storage(mount_path, path, allowed_fstypes, access):
    validate_path(mount_path)
    validate_path(path)
    if os.path.commonpath([mount_path, path]) != mount_path:
        raise StorageError("The model namespace must be beneath its configured mount.")
    if not Path(mount_path).is_dir() or not Path(path).is_dir():
        raise StorageError("The mount and model namespace must already exist as directories.")
    mount = filesystem_for(mount_path)
    if mount["target"] != mount_path:
        raise StorageError("The configured model mount is not an exact mountpoint: " + mount_path)
    if mount["fstype"] not in allowed_fstypes:
        raise StorageError("The model mount uses disallowed filesystem type " + mount["fstype"])
    namespace = filesystem_for(path)
    if (namespace["fstype"] not in allowed_fstypes
            or os.path.commonpath([mount_path, namespace["target"]]) != mount_path):
        raise StorageError("The model namespace is backed by an unexpected filesystem: " + namespace["fstype"])
    probe_access(path, access)
    return namespace["fstype"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-paths", help="validate managed local paths without writing")
    validate.add_argument("paths", nargs="+")
    check = subparsers.add_parser("check", help="validate the mount and probe namespace access")
    check.add_argument("--mount-path", required=True)
    check.add_argument("--path", required=True)
    check.add_argument("--allowed-fstype", action="append", required=True)
    check.add_argument("--access", choices=("read", "write"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-paths":
            for path in args.paths:
                validate_path(path)
        else:
            fstype = check_storage(args.mount_path, args.path, args.allowed_fstype, args.access)
            print("Model storage ready: {} ({}; {})".format(args.path, fstype, args.access))
    except (OSError, StorageError) as error:
        print("Model storage check failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
