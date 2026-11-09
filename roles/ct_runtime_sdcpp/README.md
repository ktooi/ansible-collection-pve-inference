# Role: ct_runtime_sdcpp

Build a pinned native `stable-diffusion.cpp` server in an existing GPU-ready CT,
deploy explicitly declared model files, and manage one preloaded model with systemd.

**Status: implementation and source review; deployment acceptance pending.**
The initial package mapping targets Debian 12/13 and Ubuntu 22.04/24.04.
Those targets are not a claim that GPU builds or P-H3 inference have been verified
on every OS. See [the deployment and acceptance guide](../../docs/sdcpp-deployment.md).

## Boundary and prerequisites

- Host driver installation, CT creation, device exposure and library mounts remain
  separate PVE operations. This role needs no Proxmox API token or VMID.
- The CT must provide an executable CUDA toolkit `nvcc`, compatible host-driver
  libraries and device permissions for the service account. The default toolkit
  location is `/usr/local/cuda`; set `cuda_home`/`nvcc` for another location.
- Optional `cuda_packages` come from already configured guest repositories.
  No CUDA repository or host driver is installed automatically. Do not request
  kernel-driver metapackages through this guest package list.
- GitHub source/submodules and the declared model URLs must be reachable.
  Model disk capacity, backing storage capacity and GPU memory are operator inputs.
- Default guest packages include `sudo` for Ansible's service-user build/probe
  operations, including root SSH sessions in minimal CTs. An explicitly configured
  alternative become method is still honored; initial administrative become access
  must already work if SSH does not connect as root.
- The role reuses `ct_runtime_common` with its Python venv disabled. It does not
  install PyTorch or call `ct_runtime_vllm`/`ct_runtime_launcher_common`.

The default build uses CUDA, static sd.cpp/GGML libraries and the project's patched
GGML extensions. The frontend build is disabled; Node.js/pnpm are not required.
The server is an API backend for an existing frontend. CPU-only compilation is
available for development with `ct_runtime_sdcpp_cuda: false`; this is not a
recommendation to run large P-H3 models on a CPU.

## Usage

Install the collection, add an existing CT to `ct_targets`, and provide the model
components through host variables or an sd.cpp-specific vars file:

```yaml
ct_runtime_sdcpp_cuda_architectures: "86"
ct_runtime_sdcpp_components:
  diffusion_model: /var/lib/sdcpp/models/diffusion-model.safetensors
  llm: /var/lib/sdcpp/models/text-encoder.safetensors
  vae: /var/lib/sdcpp/models/vae.safetensors
ct_runtime_sdcpp_extra_args:
  - --steps
  - "8"
```

These paths are illustrative; compatible model files must exist or be supplied by
`ct_runtime_sdcpp_artifacts`. The P-H3 profile is in
[`examples/sdcpp/`](../../examples/sdcpp/).

```bash
ansible-playbook -i inventory.ini ktooi.pve_inference.runtime_sdcpp \
  --limit ct-image -e @sdcpp-vars.yml
```

Use `ct_runtime_sdcpp_*` variables for this deployment. Passing `ct_runtime_common_*`
or artifact ownership/notification settings as extra-vars can override role-local
parameters; conflicting values are rejected before their respective operations.
The role does not stop existing vLLM services or reserve physical GPU capacity.

## Public configuration

All variable names below have the `ct_runtime_sdcpp_` prefix.

### Source and build

| Suffix | Default | Contract |
| --- | --- | --- |
| `repository` | `https://github.com/leejet/stable-diffusion.cpp.git` | Git source URL/path; use trusted source |
| `revision` | `fc350be2ceeeb859bcc201ac435591ed7d46821d` | Full lowercase 40-character commit SHA; moving branches/tags are rejected |
| `cuda` | `true` | Build CUDA; `false` selects the CPU build path |
| `cuda_home` | `/usr/local/cuda` | Provisioned guest/toolkit root |
| `nvcc` | `<cuda_home>/bin/nvcc` | Executable compiler path |
| `cuda_architectures` | `""` | Empty uses upstream detection; e.g. `"86"` for an RTX 3090 build |
| `cuda_packages` | `[]` | Optional guest toolkit packages from existing repositories |
| `packages` | OS package list | CA certificates, Git, CMake, Ninja, C++ build tools, pkg-config and sudo |
| `cmake_options` | `{}` | Additional CMake name-to-string definitions, e.g. `GGML_NATIVE: "OFF"` |
| `build_jobs` | `2` | Positive parallel build-job limit; CUDA compilation can require substantial RAM |
| `force_rebuild` | `false` | Force configure/build even when the input fingerprint matches |
| `build_environment` | `{}` | Single-line string environment mapping for Git/build commands |

The role fixes `CMAKE_BUILD_TYPE=Release`, `SD_BUILD_EXAMPLES=ON`,
`SD_SERVER_BUILD_FRONTEND=OFF`, `SD_BUILD_SHARED_LIBS=OFF`,
`SD_BUILD_SHARED_GGML_LIB=OFF`, `SD_USE_SYSTEM_GGML=OFF`,
`SD_USE_UPSTREAM_GGML=OFF`, and disables other GPU backends and dynamic GGML loading.
These options, CUDA selection and the dedicated CUDA compiler/architecture settings
cannot be overridden through `cmake_options`. In particular, upstream GGML builds
cannot load the Pruna Convrot/W4 formats used by the example.

Source submodules are checked out at their recorded commits. The build directory
fingerprint includes the source SHA, CMake settings, standard CMake/C++/nvcc version
output and build environment. The configure/build steps are skipped when these
inputs and the completed binary are unchanged. Configure/build run as the service
user; the final executable is copied atomically into a root-owned installation.
No mutable build-tree shared libraries are intentionally installed alongside it.

Custom compiler/toolkit replacement not reflected in those inputs may require
`force_rebuild`. Cached build directories are retained, not automatically pruned.
Changing the pinned revision or build settings selects the corresponding cache;
reverting them and rerunning the playbook is the binary rollback path. Model files
and service configuration must also be restored if their compatibility changed.

### Service and files

| Suffix | Default | Contract |
| --- | --- | --- |
| `user` / `group` | `sdcpp` | Dedicated Linux account/group |
| `supplementary_groups` | `[]` | Explicit existing GPU-access groups; no device chmod/GID mapping changes |
| `home` | `/var/lib/sdcpp` | Service home and working directory |
| `cache_dir` | `/var/cache/sdcpp` | User-owned Git checkout and fingerprinted builds |
| `install_dir` | `/opt/sdcpp` | Root-owned executable/launcher and build metadata |
| `service_name` | `sdcpp.service` | Unit name |
| `env_file` | `/etc/default/sdcpp` | Root/service-group readable environment file (0640) |
| `bind_host` | `127.0.0.1` | Listener address; set an appropriate private address for remote clients |
| `port` | `1234` | Listener port |
| `ld_library_path` | Toolkit `lib64` plus standard CT NVIDIA bind paths | Default `LD_LIBRARY_PATH` |
| `environment` | `{}` | Service environment overrides, including optional `CUDA_VISIBLE_DEVICES` |
| `components` | `{}` | Model component key to absolute readable file path; a `model` or `diffusion_model` is required |
| `artifacts` | `[]` | Existing `ct_model_artifacts` URL/destination/SHA256 schema, scoped to sd.cpp |

Managed service/build paths exclude whitespace, control characters, traversal and
systemd specifiers. Model paths may contain spaces and Unicode. Each configured
component is checked as the service user before the service configuration changes.
The artifact role supplies checksum validation and atomic replacement; it does not
infer compatible files, convert weights, or remove files omitted from the list.

Supported component keys are `model`, `diffusion_model`, `high_noise_diffusion_model`,
`uncond_diffusion_model`, `clip_l`, `clip_g`, `clip_vision`, `t5xxl`, `llm`,
`llm_vision`, `embeddings_connectors`, `vae`, `audio_vae`, `audio_encoder`, `taesd`
and `control_net`. The mapping preserves upstream options such as `--clip_l` and
`--llm_vision`; they do not all use hyphens.

### Engine settings and readiness

| Suffix | Default | Contract |
| --- | --- | --- |
| `backend` | `cuda0` or `cpu` | Native device/module placement string |
| `split_mode` | `layer` | Native layer/row or per-module specification |
| `max_vram` | `""` | Optional native per-device managed-memory budget string |
| `auto_fit` | `true` | Native automatic placement switch |
| `extra_args` | `[]` | List of individual argv strings; no shell evaluation |
| `min_cuda_devices` | `1` | Minimum CUDA devices visible to the service account |
| `check_ready` | `true` | Wait for a loaded model, not merely a live TCP listener |
| `readiness_host` | Listener host; loopback for wildcard listeners | Host used by the guest-side HTTP probe |
| `readiness_url` | `http://<host>:<port>/sdcpp/v1/models/status` | Native status endpoint |
| `readiness_retries` / `readiness_delay` / `readiness_timeout` | `120` / `5` / `10` | Retry count, delay and per-request timeout in seconds |

Before downloading assets, the newly built binary runs `--list-devices` with the
service user's environment and permissions. CUDA builds require the configured
device count and every explicit `cudaN` name in `backend`. Names are relative to
`CUDA_VISIBLE_DEVICES`. This is not an inference or memory-capacity test.

The launcher quotes every argument separately. Use the dedicated variables for
model components and listener/backend/split/memory/auto-fit options; informational flags such as
`--list-devices` cannot replace the service command through `extra_args`.
The role intentionally has no common LLM context/KV-cache/TP translation layer.

After changes, the service is restarted and native readiness must return HTTP 200
with JSON `state: ready`. `empty`, `loading`, an error state or a port-only response
does not pass. This proves the model context loaded, not that generation/editing
works. Disabling `check_ready` skips that assurance and must not be recorded as
deployment acceptance. Only one CLI-preloaded model service is managed by an
invocation; catalog-only operation and model lifecycle orchestration are outside
this initial role.

## Check mode, validation and acceptance

`--check` validates declaration types/paths/options and artifact checksums/destinations only. It skips package install,
source checkout/build, artifact downloads, service changes and runtime checks.
It does not predict compiled binaries or GPU memory requirements. Ansible syntax
checks and fixture tests likewise do not establish CUDA/P-H3 inference success.

The deployment gate is a real CUDA build and device probe, loaded-model readiness,
completed text-to-image and reference editing, repeated-run idempotence/restart
behavior, and measured GPU memory with the intended co-resident LLM. Until those
checks pass, the design and OS/GPU support remain provisional.

## Upstream contracts reviewed

- [Pinned CMake options](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/CMakeLists.txt)
- [Server build options](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/examples/server/CMakeLists.txt)
- [Native backend placement](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/docs/backend.md)
- [Native model-status API](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/examples/server/api.md)
