# ktooi.pve_inference

An Ansible Collection to build and operate **CT-based inference environments on Proxmox VE**.

This project is designed around practical, declarative operations with clear separation of responsibilities:
- **Proxmox host side**: GPU prerequisites and host-level configuration.
- **CT side**: runtime foundation, inference runtime installation, and systemd-managed services.

## Scope

### In scope
- Host-side GPU prerequisite setup.
- Declarative CT lifecycle management (create/update/delete).
- CT runtime foundation (Python, directories, service prerequisites).
- Runtime-specific roles (initially vLLM).
- Validation and health checks.

### Out of scope (initial phase)
- Kubernetes orchestration.
- VM-first workflows.
- Multi-node distributed inference orchestration.
- Nested Docker/Podman operation as the primary path.

## Support policy (summary)
- **Proxmox VE 8.x**: supported.
- **Proxmox VE 9.x**: beta support.
- Initial vendor/runtime focus: **NVIDIA + vLLM**.
- The structure is intentionally extensible for future **AMD** and additional runtimes.

See `docs/support-policy.md`, `docs/gpu-matrix.md`, and `docs/runtime-matrix.md` for details.

## Collection layout

```text
ktooi.pve_inference/
  galaxy.yml
  meta/runtime.yml
  docs/
  playbooks/
  roles/
  plugins/
  tests/
```

## Roles

- `host_gpu_common`
- `host_nvidia_gpu`
- `host_amd_gpu` (stub for future implementation)
- `ct_instance`
- `ct_runtime_common`
- `ct_runtime_vllm`
- `ct_runtime_sglang` (stub)
- `ct_runtime_tgi` (stub)
- `ct_runtime_ollama` (stub)
- `ct_validate`

## Typical flow

1. Prepare PVE host for GPU usage.
2. Create or update CT definition.
3. Bootstrap CT runtime common foundation.
4. Install/configure inference runtime.
5. Validate service and API readiness.

## Requirements

- Ansible Core `>=2.16`
- Collection dependency:
  - `community.proxmox >=1.6.0`

Install dependencies:

```bash
ansible-galaxy collection install -r requirements.yml
```

Example `requirements.yml`:

```yaml
collections:
  - name: community.proxmox
    version: ">=1.6.0"
```

## Example inventory groups

```ini
[pve_hosts]
pve01 ansible_host=192.0.2.10

[ct_targets]
ct-infer-01 ansible_host=198.51.100.20
```

## Example execution

```bash
ansible-playbook playbooks/host_nvidia_gpu.yml -i inventory.ini
ansible-playbook playbooks/ct_create.yml -i inventory.ini
ansible-playbook playbooks/runtime_vllm.yml -i inventory.ini
ansible-playbook playbooks/validate.yml -i inventory.ini
```

## Design notes

- Runtime roles are split by engine (`ct_runtime_*`) to keep migrations manageable.
- Host vendor differences are isolated in `host_*` roles.
- `ct_instance` manages CT lifecycle separately from runtime provisioning.
- Initial implementation favors direct process execution under systemd for clearer troubleshooting.

## Current status

This repository currently provides a clean and extensible baseline with production-oriented defaults for initial single-node deployments.

## License

MIT
