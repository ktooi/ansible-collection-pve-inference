# Optional shared storage for model files

**Status: implementation proposed; real NFS and runtime acceptance pending.**
The feature is disabled by default. Local syntax, template and fixture checks
do not establish NAS availability, cross-client locking or model-load performance.
See [ADR-007](../adr/adr-007-shared-model-storage.md).

The collection can consume a model directory on an already mounted filesystem.
Use a PVE host mount, expose it through a CT bind mount, and point the runtime's
model files or Hub cache at a prepared namespace. `ct_model_storage` checks that
namespace before deployment and adds a service-start guard. It does not mount
NFS, change CT privileges, prepare the NAS export or move existing model files.

## Storage contract

| Variable | Meaning |
| --- | --- |
| `ct_model_storage_enabled` | Opt in; default `false` |
| `ct_model_storage_mount_path` | Exact CT-visible mount point; default `/srv/models` |
| `ct_model_storage_path` | Existing namespace inside that mount, for example `/srv/models/sdcpp`; defaults to the mount path |
| `ct_model_storage_allowed_fstypes` | Allowed actual backing filesystem types; default `[nfs, nfs4]` |
| `ct_model_storage_access` | Required namespace access, `write` by default or `read` |
| `ct_model_storage_user` | Identity checked for access; runtime integrations supply their service user |
| `ct_model_storage_service_name` | Unit receiving the start guard; runtime integrations supply their service name |

Prepare the namespace and its ownership on the storage server before applying
the runtime. The role does not create that namespace or recursively change its
ownership. Keep model paths inside the intended namespace explicitly: enabling
the guard does not rewrite component paths, artifact destinations or runtime
cache variables. Mixing local and shared model files remains possible; the guard
does not impose containment on every runtime path.

Runtime roles bind the guard to their own account, service and restart handler.
Do not set `ct_model_storage_user`, `ct_model_storage_service_name` or
`ct_model_storage_notify` in a runtime's extra-vars file; conflicting values are
rejected. Those inputs remain available when invoking the storage role alone.
Keep the enabled setting in the runtime's deployment vars on subsequent runs.

With `access: write`, the check creates, syncs, renames and removes a small
temporary probe in the namespace. `access: read` checks directory access without
that write probe. Neither mode changes directory ownership or permissions.

The checks require the exact mount and an allowed backing filesystem type. This
distinguishes an NFS bind mount from a bind mount of the host's local directory
when NFS was never mounted. The service uses the same guard through
`ExecStartPre`. `RequiresMountsFor` only establishes dependencies visible to the
guest's systemd manager; it cannot mount the host's NFS filesystem. These checks
do not continuously monitor NAS health or authenticate a particular export.

Other filesystems can be explicitly allowed, but their permissions, atomic
rename, symlink and locking behavior need their own deployment tests. Merely
adding `cifs` or another type to the list is not a support certification.

## Prepare the host mount and CT bind mount

Provision the NFS export and namespaces on the NAS first. Choose the intended
writer's numeric UID/GID, taking CT user mapping into account. Use a dedicated
export/subtree and a host source path without symlinks.

The following is a separate host playbook example. Replace the inventory group,
DNS name, export and NFS version with the deployment's values. It requires the
`ansible.posix` collection and the host's NFS client utilities.

```yaml
- name: Mount model storage on the PVE hosts
  hosts: pve_model_hosts
  become: true
  tasks:
    - name: Mount the prepared model export
      ansible.posix.mount:
        src: nas.example.net:/exports/models
        path: /mnt/bindmounts/models
        fstype: nfs
        opts: rw,hard,vers=4.1,_netdev
        state: mounted
```

For a **new CT**, include the bind mount in its creation vars, preserving any
other mounts required by that CT:

```yaml
ct_instance_mounts:
  mp0: /mnt/bindmounts/models,mp=/srv/models
```

The existing `ct_instance` creation path does not reconcile arbitrary mount
changes on an already existing CT. For an **existing CT**, use a planned stop
and start after inspecting its complete configuration:

```bash
pct config 120
findmnt --mountpoint /mnt/bindmounts/models --output TARGET,SOURCE,FSTYPE,OPTIONS
```

Choose an unused `mpN` slot; never overwrite an occupied slot. The following
example assumes CT `120` and `mp1` have been checked. Stop dependent requests,
shut down the CT, and confirm `pct status 120` reports `stopped` before changing
the mount. If shutdown fails, investigate before proceeding.

```bash
pct shutdown 120 --timeout 120
pct status 120
pct set 120 --mp1 /mnt/bindmounts/models,mp=/srv/models
```

Verify the host mount still reports the expected NFS export before `pct start
120`. Inside the restarted guest, inspect `findmnt --mountpoint /srv/models
--output TARGET,SOURCE,FSTYPE,OPTIONS`, then apply the runtime vars. Plan host
boot ordering so NFS exists before the CT starts. A guest started against the
unmounted local directory may require another controlled stop/start after the
host mount is repaired; do not assume a later host mount replaces an existing
guest bind automatically.

## Connect each runtime to storage

| Runtime | Model-storage setting |
| --- | --- |
| sd.cpp | Absolute paths in `ct_runtime_sdcpp_components`; artifact `dest` values reference the same paths |
| vLLM core / Omni | `ct_runtime_vllm_hf_hub_cache_dir`, or an explicit local model directory in `ct_runtime_vllm_model` |
| TGI | `ct_runtime_tgi_hf_hub_cache_dir`, or an explicit local model directory in `ct_runtime_tgi_model` |
| SGLang | `ct_runtime_sglang_hf_hub_cache_dir`, or an explicit local model directory in `ct_runtime_sglang_model` |
| Ollama | `ct_runtime_ollama_serve_models_path`; set `ct_runtime_ollama_manage_models_directory: false` for a server-prepared directory |

### sd.cpp and checksum-pinned artifacts

Load the existing [P-H3 profile](../examples/sdcpp/p-h3-image-w4a8.yml), followed
by this storage overlay. The profile's artifact URLs and trusted SHA256 hashes
remain pinned; each artifact's `dest` already references its component path.
Replace the entire three-entry component mapping together so Ansible variable
precedence cannot drop the encoder or VAE.

```yaml
ct_model_storage_enabled: true
ct_model_storage_mount_path: /srv/models
ct_model_storage_path: /srv/models/sdcpp
ct_model_storage_allowed_fstypes: [nfs, nfs4]
ct_model_storage_access: write

ct_model_artifacts_become_user: sdcpp
ct_model_artifacts_manage_permissions: false

ct_runtime_sdcpp_components:
  diffusion_model: "{{ ct_model_storage_path }}/p-h3-image/44a0fb73f299da1bb715bdb5ff59ce3fd3c6f543/p-h3-image_w4a8.safetensors"
  llm: "{{ ct_model_storage_path }}/p-h3-image/44a0fb73f299da1bb715bdb5ff59ce3fd3c6f543/p-h3-image_text_encoder_w4a8.safetensors"
  vae: "{{ ct_model_storage_path }}/p-h3-image/44a0fb73f299da1bb715bdb5ff59ce3fd3c6f543/p-h3-image_vae_int8_convrot.safetensors"
```

For a custom manifest, keep the same relationship:

```yaml
# Entries within ct_runtime_sdcpp_artifacts:
- name: diffusion
  url: "{{ model_manifest.diffusion.url }}"
  checksum: "{{ model_manifest.diffusion.checksum }}"
  dest: "{{ ct_runtime_sdcpp_components.diffusion_model }}"
- name: encoder
  url: "{{ model_manifest.encoder.url }}"
  checksum: "{{ model_manifest.encoder.checksum }}"
  dest: "{{ ct_runtime_sdcpp_components.llm }}"
- name: vae
  url: "{{ model_manifest.vae.url }}"
  checksum: "{{ model_manifest.vae.checksum }}"
  dest: "{{ ct_runtime_sdcpp_components.vae }}"
```

`model_manifest` is caller-supplied example data, not a collection feature.
Supply immutable URLs and independently trusted `sha256:...` values for the
chosen model. A MiniMax profile uses its own complete manifest and component
mapping; changing storage does not make model components interchangeable.

The artifact options run acquisition as the selected writer and omit explicit
owner/group/mode management. With `root_squash`, prepare `/srv/models/sdcpp` so
that the mapped `sdcpp` identity can create directories and files there. Retain
local defaults for `ct_runtime_sdcpp_cache_dir` and `ct_runtime_sdcpp_install_dir`:
source/build objects and executables do not need to live on NFS.

Use one consistent writer identity and verify the serving account can read the
result. Ansible still performs internal attribute preservation during atomic
replacement; cross-owner replacements can lose prior modes/ACLs when NFS denies
those operations. Disabling explicit metadata management is not an ACL-preservation
guarantee. Prefer new versioned paths over overwriting another writer's files.

### Hugging Face model caches

For a vLLM example, prepare the namespace and its `hub` directory with the
runtime identity's access, then configure:

```yaml
ct_model_storage_enabled: true
ct_model_storage_mount_path: /srv/models
ct_model_storage_path: /srv/models/vllm
ct_model_storage_access: write
ct_runtime_vllm_hf_hub_cache_dir: "{{ ct_model_storage_path }}/hub"
```

Use the equivalent `ct_runtime_tgi_hf_hub_cache_dir` or
`ct_runtime_sglang_hf_hub_cache_dir` for those roles. The new settings emit
`HF_HUB_CACHE` and the legacy Hub-cache environment name for compatibility,
without relocating `HF_HOME`. Existing vLLM callers retain the legacy
`ct_runtime_vllm_hf_cache_dir` behavior when the new variable is unset; conflicting
old/new cache settings are rejected. Use only the new setting for shared caches;
even matching old/new values are rejected because the legacy setting also moves
the credential home.

`HF_HOME` also contains authentication state. Keep it, token files, runtime
environments, compiler caches and temporary files local. Copying only a Hub
`snapshots` directory may leave dangling symlinks; preserve its referenced blobs
and cache layout. Do not garbage-collect shared blobs while active runtimes
still use them.

### Ollama

Prepare the configured model directory before applying the role:

```yaml
ct_model_storage_enabled: true
ct_model_storage_mount_path: /srv/models
ct_model_storage_path: /srv/models/ollama
ct_model_storage_access: write
ct_runtime_ollama_serve_models_path: "{{ ct_model_storage_path }}"
ct_runtime_ollama_manage_models_directory: false
```

For read-only serving, use `ct_model_storage_access: read`, prepopulate all
required data and disable acquisition (`ct_runtime_ollama_pull_model: false`
for Ollama; omit artifact downloads for sd.cpp). This setting checks access; it
does not remount the filesystem read-only or make a runtime's download behavior
read-only. Test each runtime against the prepared data before restricting writes.

## Operational tradeoffs

- **Identity and permissions:** NFS commonly squashes root. Match numeric IDs on
  the server, host and CT mapping, or deliberately configure a writer/shared
  group policy. A matching account name alone is insufficient. Do not weaken
  the export with `no_root_squash` simply to allow Ansible to chown files.
- **Concurrent updates:** start with one controlled writer per namespace. Use
  immutable revisions/versioned destinations and serialize deployments that
  update the same paths. Atomic artifact replacement is not a distributed lock.
  Hugging Face has fixed shared-download races on filesystems with broken
  locking; verify the installed library version and actual client/server locks.
- **Performance:** shared storage avoids storing/downloading a separate copy for
  each CT, but cold loads and simultaneous starts consume NAS/network bandwidth.
  Later file or mapped-page access can still depend on NFS. Measure cold and warm
  loads separately. Moving weights does not reduce required RAM or GPU VRAM.
- **Outages:** a hard NFS mount can block I/O while the server is unavailable.
  Startup guards prevent common local-directory fallback mistakes but are not
  health monitors. `soft`/`softerr` are not general fixes; the NFS manual warns
  that they can cause silent data corruption in some cases.
- **Persistence and backups:** deleting/recreating a CT does not copy or remove
  the externally managed model namespace. Bind-mounted content is excluded from
  `vzdump`; use NAS snapshots/backups or a reproducible acquisition manifest.
  Provision the same intended export/path on any migration destination host.

This feature adds no distributed writer lock, model garbage collection,
automatic local staging, filesystem migration or cache-format conversion.
Existing local files remain where they were. Move or reacquire them through an
explicit storage operation and verify checksums before switching the runtime.

## Target acceptance

Record the collection revision, PVE/guest/NAS versions, mount source/options,
numeric UID/GID mapping, runtime version and model revisions. Verify a real
download and inference, repeat deployment without unwanted changes, and planned
host/CT restart behavior. On an isolated trial, verify that a missing/wrong
mount prevents acquisition and service start, and that no local fallback files
are created. Test outage/recovery and concurrent writers only in a controlled
window. Repository tests do not substitute for these checks.

## References

- [Proxmox CT bind mounts, identity mapping and backups](https://github.com/proxmox/pve-docs/blob/master/pct.adoc)
- [Ansible mount module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/posix/mount_module.html)
- [Hugging Face environment variables](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables)
- [Hugging Face cache structure](https://huggingface.co/docs/huggingface_hub/en/guides/manage-cache)
- [Hugging Face concurrent-download fix](https://github.com/huggingface/huggingface_hub/pull/4306)
- [NFS export identity mapping](https://man7.org/linux/man-pages/man5/exports.5.html)
- [NFS mount and recovery semantics](https://man7.org/linux/man-pages/man5/nfs.5.html)
- [systemd mount dependencies and conditions](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit)
- [Linux bind mounts](https://man7.org/linux/man-pages/man8/mount.8.html)
- [findmnt filesystem inspection](https://man7.org/linux/man-pages/man8/findmnt.8.html)
