# Architecture

## Goal
Provide a maintainable Ansible architecture for CT-based inference workloads on Proxmox VE.

## Responsibility boundaries

### Host layer
- Host prerequisites.
- GPU vendor specific setup.
- Host tuning that should not be managed from inside CT.

### CT lifecycle layer
- Declarative container definition and lifecycle control.
- Resource sizing and feature flags.
- Device exposure/bind mount definitions.

### CT runtime layer
- Runtime foundation (packages, Python, user, paths).
- Runtime-specific installation/configuration.
- Service management via systemd.

### Validation layer
- GPU visibility checks.
- Runtime and service health checks.
- Optional API smoke tests.

## Extension model
- Add GPU vendors via new `host_*` roles.
- Add runtime engines via new `ct_runtime_*` roles.
- Keep common logic in `host_gpu_common` and `ct_runtime_common`.
