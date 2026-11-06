# ADR-004: Proxmox creation completion and recovery

Status: Accepted

## Context

A CT creation finished with `status=stopped` and `exitstatus=WARNINGS: 1`, but
the legacy Proxmox module waited until timeout. The role then recovered using
only `pct status`, which cannot distinguish a completed creation from a partial
configuration left by a failed or still-running task.

## Decision

- Call `community.proxmox.proxmox` directly and declare >=1.6.0 in `galaxy.yml`.
  That implementation accepts warning-completed tasks. Existing documentation
  and runtime metadata already requested this dependency; the install manifest
  did not declare it. Align the Ansible minimum with its requirement, >=2.17.
- Pass `update: false` explicitly to preserve creation-only handling of existing
  CTs despite the newer module's default of updating them.
- Recover from a creation timeout only when the returned UPID has stopped with
  `OK` or `WARN*` and the local CT exists. Missing task IDs, failed/running tasks,
  and unreadable results stop configuration. Keep the original API error in
  diagnostics and recognize both old and new creation-timeout wording.

## Consequences

Warning-completed creations can finish promptly. Recovery requires read access
to the task result through `pvesh` on the SSH target. A timeout alone does not
justify configuring or starting a CT. Existing CT creation settings remain
unchanged, while the separate managed NVIDIA passthrough block remains editable.
