# Deploy stable-diffusion.cpp in a GPU CT

**Status: deployment validation pending.** The user approved this implementation
direction, with final design acceptance deferred until actual deployment tests.
[ADR-006](../adr/adr-006-sdcpp-runtime.md) remains Proposed. Source review, syntax
checks and local test fixtures do not establish CUDA inference on the target CT.

The `ct_runtime_sdcpp` role builds a pinned native `sd-server` and manages its
isolated systemd service. It reuses common account/directory preparation and
checksum-pinned model artifacts. vLLM core/Omni retain their existing role and
defaults. No PVE API token is required by the runtime playbook, and it does not
create CTs, update host drivers or stop other GPU workloads.

## Scope and fixed inputs

| Item | Initial trial |
| --- | --- |
| Execution | Native executable and systemd in an existing GPU CT |
| Guest OS path | Debian 12/13 or Ubuntu 22.04/24.04; target deployment not yet validated |
| GPU backend | CUDA; explicitly provisioned compatible host driver and guest toolkit |
| sd.cpp revision | `fc350be2ceeeb859bcc201ac435591ed7d46821d` |
| Model example | [P-H3 W4A8/INT8](../examples/sdcpp/p-h3-image-w4a8.yml) |
| Model revision | `PrunaAI/P-H3-Image-Comfy@44a0fb73f299da1bb715bdb5ff59ce3fd3c6f543` |
| Default service | `sdcpp.service` |
| Default endpoint | `http://127.0.0.1:1234` |

The generic role does not select P-H3 by default. A caller supplies model
components and any matching artifacts. See the [role contract](../roles/ct_runtime_sdcpp/README.md)
for complete variables.

The initial implementation has a Debian/Ubuntu package path. Do not infer
RHEL-family, AMD, Vulkan, ordinary-VM or bare-metal support from other roles'
support statements.

## Prepare the target

Use the existing host GPU and CT lifecycle playbooks to prepare a CT with
working SSH/become, the intended GPU devices, driver-library access and sufficient
storage. The model files in the example total about 20.1 GB; source/build
directories, package caches and outputs require additional capacity. Check the
backing pool's actual capacity as well as the CT filesystem.

Record the following inside the intended CT:

```bash
cat /etc/os-release
nvidia-smi --query-gpu=index,uuid,name,driver_version,memory.total,memory.free --format=csv
/usr/local/cuda/bin/nvcc --version
df -h /opt /var/lib /var/cache
```

Set `ct_runtime_sdcpp_cuda_home` to the actual toolkit path. The CUDA version
displayed by `nvidia-smi` describes driver support; it is not a substitute for
checking `nvcc`. The host driver's compatibility with the selected toolkit and
the target GPU remains an acceptance input.

The role does not choose a host driver or add a CUDA package repository
automatically. A preprovisioned toolkit is the default. An explicit
`ct_runtime_sdcpp_cuda_packages` list can install guest packages from already
configured repositories; use toolkit/userspace packages compatible with any
host-library mounts. Do not use driver metapackages to manage the PVE kernel
from inside a CT.

For the four-GPU example, confirm that all four intended devices are visible.
It sets `ct_runtime_sdcpp_min_cuda_devices: 4` and compiles for architecture 86
(RTX 3090). Change the architecture setting for a different GPU generation.
Review available capacity while the LLM and other services are in their intended
state. Nothing in this profile reserves VRAM or changes the LLM's memory budget.

### Choose build parallelism

The default native build uses at most two parallel jobs. To use the CPU count
available to the build user inside the CT, add this to the sd.cpp vars file:

```yaml
ct_runtime_sdcpp_build_jobs: auto
```

For example, a CT whose `nproc` reports 8 uses `--parallel 8`; it does not gain
access to additional PVE host CPUs. Inspect the same probe on the CT if needed:

```bash
sudo -u sdcpp env -u OMP_NUM_THREADS -u OMP_THREAD_LIMIT nproc
```

The service account must already exist for this manual command. The role creates
it before detection and logs the resolved job count before compilation. `auto`
uses CPU affinity/cpuset; cgroup v2 quota detection requires a sufficiently recent
`nproc` (added in GNU coreutils 9.8). If the CT has only a quota restriction or RAM
is constrained, set a positive number such as `4` instead. CUDA compiler processes
can consume substantial RAM, so higher parallelism does not guarantee a faster
build. Link/dependency phases can also use fewer CPUs than the selected maximum.

Changing only this variable does not create a different build directory. After
a failed/interrupted build, retain the source/build cache and rerun the playbook
to reuse completed objects. Confirm that the original remote CMake/Ninja/compiler
processes have exited before starting another build in that directory; changing
vars cannot alter an already running command. A completed build is not rebuilt
just because its job limit changes. `force_rebuild` is unnecessary when the build
is incomplete. For the full contract, see [build parallelism](../roles/ct_runtime_sdcpp/README.md#build-parallelism).

## Install and apply the reviewed collection

From the reviewed collection checkout, create a project-isolated installation.
This avoids accidentally using another installation with the same collection
version label:

```bash
sdcpp_collection_stage="$(mktemp -d)"
ansible-galaxy collection build --output-path "$sdcpp_collection_stage"
ansible-galaxy collection install \
  "$sdcpp_collection_stage"/ktooi-pve_inference-*.tar.gz \
  -p "$sdcpp_collection_stage/collections"
export ANSIBLE_COLLECTIONS_PATH="$sdcpp_collection_stage/collections"
ansible-galaxy collection list ktooi.pve_inference
```

The inventory must contain the CT in `ct_targets`. Replace the inventory path
and `ct-sdcpp` alias below with the intended guest, not the PVE node.
Copy the example into your Ansible project and adjust the toolkit, paths,
service identity and GPU settings before applying it. The example path below is
relative to the collection checkout.

```bash
ansible-playbook -i /path/to/inventory.ini \
  ktooi.pve_inference.runtime_sdcpp \
  --limit ct-sdcpp \
  -e @examples/sdcpp/p-h3-image-w4a8.yml \
  --syntax-check

ansible-playbook -i /path/to/inventory.ini \
  ktooi.pve_inference.runtime_sdcpp \
  --limit ct-sdcpp \
  -e @examples/sdcpp/p-h3-image-w4a8.yml
```

Use sd.cpp-specific overrides for this invocation. Do not pass an existing
vLLM deployment vars file as an additional extra-vars file: generic common-role
or artifact extra-vars can override role-scoped values. The role rejects
conflicting account/path/artifact settings before their respective operations.

A syntax check does not build the runtime, download/validate model contents or
exercise a GPU. Check mode validates declarations and skips all deployment
actions, including GPU and model-readiness checks.

The runtime role installs/builds the selected revision, deploys declared model
files, validates component paths, renders the service and waits for the native
model status. A ready model is still not a completed generation.

## P-H3-specific behavior

The example uses a W4A8 diffusion transformer, a W4A8 bundled text encoder with
its vision tower/connector, and the P-H3 INT8 single-frame image VAE. The
MiniMax-H3 video VAE is incompatible.

The pinned sd.cpp build uses its patched GGML for direct loading of Convrot INT8
and packed W4 formats. `SD_USE_UPSTREAM_GGML=ON` rejects those formats; GGUF
conversion is not mandatory. The upstream P-H3 guide's command uses INT8
diffusion with BF16 encoder/VAE. The W4A8 combination in this example requires
its own end-to-end checks.

sd.cpp does not implement Pruna's prompt enhancement stage. Supply a detailed
prompt or add an explicit upstream expansion step. An arbitrary LLM is not a
verified substitute for the trained prompt upsampler.

Keep CFG 1, Euler, eight steps and `--sigmas p-h3-image`. The sample starts at
1024×1024 to limit the first trial's working set. The upstream P-H3 reference
size is 2912×2912; dimensions must be divisible by 32. Repeat acceptance at the
resolution and reference-image workload actually required.

## Four-GPU placement

The example requests:

```text
--backend 'diffusion=cuda0&cuda1&cuda2&cuda3,te=cuda0&cuda1&cuda2&cuda3,vae=cuda1'
--split-mode layer
--auto-fit off
```

This is transformer-block partitioning for diffusion and the dominant text
encoder. It is not four complete model replicas. Device names must match
`sd-server --list-devices` inside this CT; any CUDA visibility mapping also
affects those names.

Layer placement follows available memory and compute headroom. The first
device also holds non-block weights and graph input/output. VAE runs on one
device, placed on `cuda1` in this profile. Consequently, four-way placement does
not promise equal 25% VRAM use.

Upstream auto-fit runs before the final split plan and can conservatively count
the full component on every device, choosing CPU/disk placement even when a
split would fit. The example disables auto-fit to retain explicit split-device
residency. Review capacity before doing so. `ct_runtime_sdcpp_max_vram` can set
per-device managed budgets, but it is neither a physical hard cap nor a
reservation against other processes.

Start with layer mode. Row splitting has different communication and budget
accounting behavior and is not part of this profile's acceptance. ComfyUI's
roughly 21 GB published peak is not an sd.cpp measurement and cannot be divided
by four to estimate each GPU's use.

## Verify service and model readiness

Inside the CT:

```bash
systemctl is-active sdcpp.service
journalctl -u sdcpp.service -b -n 100 --no-pager
curl --fail-with-body http://127.0.0.1:1234/sdcpp/v1/models/status
curl --fail-with-body http://127.0.0.1:1234/v1/models
```

The native status must report `state: ready`. An HTTP listener with `empty`,
`loading` or `error` is not a loaded model. The compatibility model ID is
currently `sd-cpp-local`; the model list does not implement vLLM-style model
dispatch.

For testing from another machine with the default loopback bind:

```bash
ssh -N -L 1234:127.0.0.1:1234 YOUR_SSH_USER@YOUR_CT_ADDRESS
```

Use the local forwarded endpoint in subsequent requests. If using Traefik/SSO,
select an appropriate private bind address and authenticated proxy route
explicitly. The role does not deploy the proxy or authentication.

### Recover from 226/NAMESPACE

The reported `ct-image` trial reached model-file verification but systemd failed
before starting the launcher:

```text
Failed to set up mount namespacing: Permission denied
Failed at step NAMESPACE spawning /opt/sdcpp/bin/start-sd-server
status=226/NAMESPACE
```

This is a service execution-environment failure, before model loading. The original
unit hardcoded `PrivateTmp=true`, which requests a new filesystem namespace. That
request can be denied by a restricted CT. The journal alone does not identify the
specific host policy (for example, an AppArmor rule). Increasing HTTP retries or
rebuilding the binary cannot repair this pre-execution failure.

The role now defaults `ct_runtime_sdcpp_private_tmp` to `false`. Update the
collection and use the following runtime setting for an affected CT:

```yaml
ct_runtime_sdcpp_private_tmp: false
```

Rerun the normal runtime playbook. The unit change triggers a daemon reload and
service restart. This setting does not change the native build fingerprint or
model checksums, so it does not itself require recompilation or model downloads.
Set it to `true` only when service mount namespaces have been verified in the CT.
The dedicated account, `NoNewPrivileges=true` and `UMask=0027` remain in effect;
only per-service `/tmp` and `/var/tmp` isolation is disabled. No change to the CT's
privileged/unprivileged mode, nesting or host AppArmor policy is needed for this
role-level adjustment.

For an immediate trial before updating the collection, run this inside the
affected CT as root. It stops the restart loop and adds one temporary drop-in
under `/run` (cleared by a CT reboot):

```bash
systemctl stop sdcpp.service

install -d -m 0755 /run/systemd/system/sdcpp.service.d
cat > /run/systemd/system/sdcpp.service.d/90-sdcpp-lxc-namespace.conf <<'EOF'
[Service]
PrivateTmp=false
EOF

systemctl daemon-reload
systemctl reset-failed sdcpp.service
systemctl start sdcpp.service

systemctl show sdcpp.service \
  -p PrivateTmp -p NoNewPrivileges -p ActiveState -p SubState \
  -p MainPID -p ExecMainStatus -p NRestarts
journalctl -u sdcpp.service --since '-2 minutes' -n 100 --no-pager
```

Confirm that `PrivateTmp` is disabled, the namespace failure no longer recurs,
and the server proceeds to model loading. Initial CLI model loading happens before
HTTP listen, so an immediate API connection refusal can still occur while loading.
After the listener starts, require the native model status to return `state=ready`;
successful service start alone is not deployment acceptance.

After applying the updated role with `private_tmp: false`, remove only this
temporary workaround once the managed unit itself contains the new setting:

```bash
if grep -Fxq 'PrivateTmp=false' /etc/systemd/system/sdcpp.service; then
  rm -f -- /run/systemd/system/sdcpp.service.d/90-sdcpp-lxc-namespace.conf
  systemctl daemon-reload
fi
```

Other local drop-ins are preserved. A later opt-in to `private_tmp: true` requires
this temporary override to be absent. If `226/NAMESPACE` persists with the setting
disabled, inspect `systemctl cat sdcpp.service` for additional namespace settings
and obtain the relevant host-side denial logs before considering host changes.

The target failure is observed; recovery and P-H3 readiness after this change
still require a target rerun. Local template/syntax tests cannot establish that
the CT's complete GPU/model workload succeeds. See the official
[PrivateTmp and execution-status reference](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).

## Generate and inspect an image

While testing, record memory in another terminal on the GPU host or CT:

```bash
nvidia-smi \
  --query-gpu=timestamp,index,uuid,memory.used,memory.free,utilization.gpu \
  --format=csv -l 1 > sdcpp-gpu.csv
```

Stop this foreground sampler with Ctrl-C after the workload. Record the idle
baseline and peak during model loading, prompt encoding, sampling and VAE work.

The compatibility image API is synchronous. Its timeout is a test limit, not a
latency expectation:

```bash
curl --fail-with-body --max-time 1200 \
  http://127.0.0.1:1234/v1/images/generations \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "A documentary photograph of a red ceramic teapot on a light oak table beside a window, soft morning light from the left, visible natural ceramic texture, realistic proportions, uncluttered background.",
    "n": 1,
    "size": "1024x1024",
    "output_format": "png"
  }' \
  -o ph3-generation.json

python3 - <<'PY'
import base64
import json
from pathlib import Path

response = json.loads(Path("ph3-generation.json").read_text())
image = base64.b64decode(response["data"][0]["b64_json"], validate=True)
if not image.startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit("The response is not a PNG image")
Path("ph3-generation.png").write_bytes(image)
print("Wrote ph3-generation.png:", len(image), "bytes")
PY
```

Open `ph3-generation.png` and inspect it. Saving valid image bytes alone is not
a quality check. Repeat with `"size": "2912x2912"` only after checking available
memory, then record the intended production resolution and latency.

## Test reference-image editing separately

Prepare `source.png` as the image to edit and `reference.png` as the visual
reference. Reference numbering follows upload order:

```bash
curl --fail-with-body --max-time 1200 \
  http://127.0.0.1:1234/v1/images/edits \
  --form-string 'prompt=Edit <Picture 1>. Replace the teapot with the teapot shown in <Picture 2>, preserving the table, camera viewpoint, lighting direction and background of <Picture 1>.' \
  -F 'image[]=@source.png' \
  -F 'image[]=@reference.png' \
  --form-string 'n=1' \
  --form-string 'size=1024x1024' \
  --form-string 'output_format=png' \
  -o ph3-edit.json

python3 - <<'PY'
import base64
import json
from pathlib import Path

response = json.loads(Path("ph3-edit.json").read_text())
image = base64.b64decode(response["data"][0]["b64_json"], validate=True)
if not image.startswith(b"\x89PNG\r\n\x1a\n"):
    raise SystemExit("The response is not a PNG image")
Path("ph3-edit.png").write_bytes(image)
print("Wrote ph3-edit.png:", len(image), "bytes")
PY
```

Inspect whether the requested reference was used and the preserved scene stayed
consistent. Test the actual number and sizes of reference images required by
the application; editing can have a different memory peak from text-to-image.

Existing ComfyUI nodes need a separate compatibility test for request fields,
multipart inputs, timeouts and base64 results. OpenAI-shaped endpoints do not
guarantee a drop-in replacement for every vLLM client.

## Repeat-run and recovery checks

Re-run the same playbook/profile. Confirm that unchanged source/build settings
do not rebuild the executable and that unchanged configuration/artifacts do not
restart the service unnecessarily. Check the play recap, build logs and service
start time. Confirm the service returns to model-ready after a planned restart.

Before updating an accepted deployment, retain its collection commit, sd.cpp
revision/build inputs, model profile/checksums and previous service settings.
To revert a failed update, restore those variables and reapply the same
playbook. The runtime keeps fingerprinted build directories; a matching previous
directory can reuse existing build outputs, but changing the source checkout
can still trigger configuration and compilation. A previous model profile must
also be restored explicitly. Removed artifact declarations do not delete old
model files.

To withdraw a newly installed trial service, run inside its CT:

```bash
sudo systemctl disable --now sdcpp.service
```

Use the configured unit name if changed. This leaves models/builds available for
inspection or retry; it does not stop vLLM or change the host driver. First-time
withdrawal and rollback to a previously accepted deployment are different
operations.

## Acceptance record

All target-deployment items below are pending until actual results are recorded.
Keep [ADR-006](../adr/adr-006-sdcpp-runtime.md) Proposed until reviewed evidence
supports acceptance.

| Evidence | Record from the target |
| --- | --- |
| Host/guest | PVE version, CT OS, kernel/driver, device permissions and library exposure |
| Build | Collection commit, sd.cpp commit, compiler/toolkit versions and build settings |
| Models | Revision, component names, hashes, precision and disk use |
| Placement | Visible device UUIDs, backend/split/auto-fit settings, budgets and observed placement |
| Generation | Completed text-to-image request, inspected output, resolution and latency |
| Editing | Completed reference-image request, inspected output, reference count/sizes and latency |
| Memory | Idle and peak VRAM for each GPU during load and each workload |
| LLM co-residency | Repeat the intended image workload with the intended LLM active; record both workloads' results |
| Lifecycle | Repeat-run changes/restarts, planned restart recovery and rollback result |
| Frontend | Shared ComfyUI generation/editing calls through the intended API/proxy path |

Static checks and local fixtures should be recorded separately from these GPU
results. A failed build, OOM, unsupported component or client mismatch is a
reason to revise the profile or implementation before accepting the design.

## Upstream references

All sd.cpp links below are pinned to the inspected source revision.

- [P-H3 guide](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/docs/p_h3_image.md)
- [P-H3 server recipe](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/examples/server/recipes/p-h3-image.json)
- [Backend placement and auto-fit](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/docs/backend.md)
- [Packed quantization formats](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/docs/int8_convrot.md)
- [Server API](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/examples/server/api.md)
- [Pinned model repository](https://huggingface.co/PrunaAI/P-H3-Image-Comfy/tree/44a0fb73f299da1bb715bdb5ff59ce3fd3c6f543)
