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
- Runtime foundation (packages, user, paths, optional runtime Python environment).
- Runtime-specific installation/configuration.
- Service management via systemd.
- Optional `ct_model_storage` validation of already-mounted model namespaces and
  runtime startup guards. Host NFS mounts and CT bind attachment remain in their
  infrastructure layers; credentials, virtualenvs and build caches remain local.

Shared model paths are explicit runtime/artifact inputs. See
[ADR-007](../adr/adr-007-shared-model-storage.md) and the
[shared storage guide](shared-model-storage.md) for namespace permissions,
root-squash behavior and deployment-test requirements.

### Validation layer
- GPU visibility checks.
- Runtime and service health checks.
- Optional API smoke tests.

## Extension model
- Add GPU vendors via new `host_*` roles.
- Add runtime engines via new `ct_runtime_*` roles.
- Keep common logic in `host_gpu_common` and `ct_runtime_common`.

## Native image runtime extension

`ct_runtime_sdcpp` is a separate engine role within this collection. It shares
account/directory preparation and model artifact delivery, while owning its
pinned native build, CLI, service and model-readiness checks. It does not use
LLM context/KV/TP launcher settings or run the vLLM role for CUDA prerequisites.
Core/Omni remain in `ct_runtime_vllm` as specified by ADR-002.

Common Python venv creation remains enabled for existing callers and can be
disabled by native runtimes. Model-specific component files, checksums and
sampling/placement choices belong in examples or caller variables.

The implementation direction is approved, but final acceptance awaits actual
deployment tests. See [ADR-006](../adr/adr-006-sdcpp-runtime.md) and the
[sd.cpp acceptance procedure](sdcpp-deployment.md#acceptance-record).
Collection separation, if later required, should distinguish PVE infrastructure
from reusable inference runtimes across modalities; it does not isolate GPU memory.
