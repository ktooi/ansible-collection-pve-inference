# Share host NVIDIA GPUs between STT and image CTs

This example creates one CT per model and exposes the same available host GPUs
to both. With four RTX 3090 cards, `ct_instance_nvidia_gpus: all` exposes GPU
device nodes 0 through 3 to each CT. It does not reserve VRAM or automatically
distribute a model across those GPUs.

## Prepare the host and inventory

1. Prepare the GPU host with `playbooks/host_nvidia_gpu.yml`. Verify the expected
   physical GPU inventory and core/UVM character devices before CT creation.
2. Use your existing `pve_hosts` inventory, API credentials, node, storage, SSH
   key, and CT preparation settings. Set `ct_instance_ostemplate` to a downloaded
   template compatible with your selected runtime. The documented Omni pairing
   uses Python 3.12; Ubuntu 24.04 is one template option. The default Debian 12
   template does not itself supply Python 3.12.
   These examples use privileged CTs with the `video` group matching the host GPU
   device GID. The runtime user is `infer`, and its systemd service uses
   `Group=video` for access to host `root:video` GPU nodes. An unprivileged CT
   requires a suitable device/user/group mapping instead of assuming this setup.
3. Adapt the example VMIDs, IPs, subnet, gateway, and bridge in `ct-stt.yml` and
   `ct-image.yml` to your site. Both CTs must reside on the GPU host whose device
   nodes are being selected.
4. Use the complete `host_vars/ct-stt.yml` and `host_vars/ct-image.yml` as the
   matching files under your inventory, adapting their CT addresses and SSH key
   paths. They include runtime foundation, venv/service paths, package versions,
   CUDA management, model tuning, cache, and logging settings. Add the hostnames
   to `ct_targets`:

```ini
[ct_targets]
ct-stt
ct-image
```

Copy the complete files without merging their model settings into `group_vars`:

```bash
mkdir -p inventory/host_vars
cp examples/shared-nvidia/host_vars/ct-stt.yml inventory/host_vars/ct-stt.yml
cp examples/shared-nvidia/host_vars/ct-image.yml inventory/host_vars/ct-image.yml
```

Use a fresh Python 3.12 venv at the configured path. The common role does not
replace an existing venv created by a different Python version.

Keep model-specific settings in those host files, rather than putting LLM parser,
MTP, or extra CLI flags in shared CT group variables. Each CT has its own virtual
environment and service, so both can listen on port 8000 at their respective IPs.

The CT creation files (`ct-stt.yml` and `ct-image.yml` in this directory) apply to
the PVE inventory host. The runtime host files belong under
`inventory/host_vars/` and contain CT SSH connection settings; use those through
the `ct_targets` inventory during runtime deployment. Passing a runtime host file
as extra variables to the PVE creation play would change its SSH destination.

## Host-CUDA prerequisites

The CT creation examples mount the host's `/usr/local/cuda` toolkit at the same
path and bind the host driver-library files. They leave the `/usr/local/nvidia`
toolkit alias disabled. The runtime examples use that toolkit as `CUDA_HOME`,
keep driver libraries on their own search path, and disable CT-side CUDA package
and nvcc auto-installation. Model Python packages are installed in each CT's venv.

Provide host-compatible NVIDIA driver userspace, including `nvidia-smi` and any
required driver libraries, in each CT before runtime deployment. The toolkit
mount and two driver-library binds alone do not provide the entire driver
userspace installation. If installing that userspace with APT, prepare it before
enabling the file-level binds, or set
`ct_instance_nvidia_bind_driver_libraries: false` and manage the compatible CT
driver userspace yourself. This avoids replacing files that are bind-mounted
from the host. The examples enable the `nvidia-smi`, device, libcuda,
nvcc, and torch preflights. The role's documented version-pin relaxation from
strict to count still applies to its torch probe.

If the host toolkit lives elsewhere, update `ct_instance_host_cuda_toolkit_path`
in the creation file and `ct_runtime_vllm_cuda_home` plus its mount hint in the
corresponding runtime host file. After changing existing CT mounts, rerun the CT
creation playbook; the managed-block restart policy applies.

## Create the CTs and deploy their runtimes

From the Collection checkout, replace `pve01` with the GPU host's inventory name:

```bash
ansible-playbook -i inventory/ playbooks/ct_create.yml -l pve01 \
  -e @examples/shared-nvidia/ct-stt.yml
ansible-playbook -i inventory/ playbooks/ct_create.yml -l pve01 \
  -e @examples/shared-nvidia/ct-image.yml
```

CT creation runs on the PVE inventory host, one CT definition per invocation.
Complete the host-CUDA prerequisites above and confirm the CT driver/toolkit
configuration before deploying its runtime. The GPU-selection setting manages
device exposure only.

```bash
ansible-playbook -i inventory/ playbooks/runtime_vllm.yml -l ct-stt,ct-image
```

For subsets, change either CT definition to a list such as `[0, 2]` and rerun its
CT creation playbook. Lists may overlap. The role replaces its managed block and
uses the existing restart setting when that block changes. Rerun after host
driver/device changes to refresh the discovered major/minor numbers.

## Verify actual requests

Check GPU access as the service user inside each CT, then send representative
requests to both services:

```bash
curl --fail http://192.0.2.120:8000/v1/audio/transcriptions \
  -F model=openai/whisper-large-v3-turbo -F file=@speech.wav \
  -F language=ja -F response_format=json

curl --fail http://192.0.2.121:8000/v1/images/generations \
  -H 'Content-Type: application/json' \
  -d '{"model":"stabilityai/stable-diffusion-xl-base-1.0","prompt":"A cat in a garden","size":"1024x1024"}'
```

The STT sample uses one-way tensor parallelism despite having all GPUs available.
Actual GPU usage depends on the model and runtime configuration. For Omni,
model-specific parallelism/offloading arguments belong in
`ct_runtime_vllm_extra_args`; core vLLM's memory-utilization and parallelism
variables are not automatically passed to Omni.

The illustrative STT memory budget is not a hard CT VRAM quota. Size both models
against measured concurrent peak memory, including temporary buffers. Larger
image models such as Qwen-Image may require multiple GPUs, offloading, or a
supported quantized configuration. These examples have not been validated with
live STT/image inference on the target GPUs.
