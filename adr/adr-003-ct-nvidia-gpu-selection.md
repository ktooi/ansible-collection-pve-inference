# ADR-003: CT NVIDIA GPU selection and shared access

- Status: Accepted
- Date: 2026-11-05

## Context

Different model services need independent CT runtimes while sharing or selecting
host GPUs. Fixed GPU 0/1 mounts and guessed UVM majors do not describe this
configuration. The generated block also previously hid explicit raw overrides.

## Decision

Keep device exposure in `ct_instance`, with `ct_instance_nvidia_gpus` accepting
`all` or a non-empty list of unique host device numbers. Its default `null`
retains available legacy GPU 0/1 nodes. Overlapping selections are allowed.

Use a read-only `nvidia_device_info` module to inspect character devices and
derive exact cgroup major/minor pairs on each role run. Validate selected devices
before CT lifecycle changes. A non-empty raw passthrough block takes complete
precedence and bypasses discovery and feature-generated entries.

## Consequences

Existing configurations keep their default GPU selection. Operators can expose
the same four GPUs to STT and image CTs without hand-writing device rules.
Driver/device-number changes require rerunning the role; the existing restart
policy applies when the managed configuration changes. Unmanaged entries remain
outside this role's block.

Device exposure does not configure model parallelism, set container CUDA
ordinals, reserve compute, or partition VRAM. Those remain runtime/application
concerns, preserving ADR-001's role boundaries.
