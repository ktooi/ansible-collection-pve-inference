# ct_model_storage

Validate an already mounted shared model filesystem and optionally guard a
runtime's systemd startup. The role is disabled by default. It works with native
model files and runtime-managed caches; it does not select a runtime or change
its model/cache paths.

The collection's sd.cpp, vLLM core/Omni, TGI, SGLang and Ollama roles include this
role before model acquisition or service configuration. Set the shared-storage
path/access variables in their deployment vars. They provide their account,
service and restart-handler binding and reject conflicting extra-vars for those
three inputs. Use the explicit account/service inputs below for standalone use.

## Prerequisites and boundaries

- Mount shared storage on the PVE host and expose it to the CT before invoking
  this role. The mount must already exist at the configured CT path.
- Provision the namespace on the storage server with the service account's
  effective numeric UID/GID or suitable ACLs. Create the service account first.
- Python 3 and util-linux `findmnt` must be available in the CT.
- Set the runtime's own component/cache path variables to the namespace.

This role does not mount/unmount filesystems, attach CT bind mounts, change CT
privileges, create directories on shared storage, change shared ownership,
migrate files, or coordinate multiple writers. Source trees, virtual
environments, compiled kernels and credentials should retain their separate
local paths.

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `ct_model_storage_enabled` | `false` | Enable mount and namespace validation |
| `ct_model_storage_mount_path` | `/srv/models` | Exact existing mountpoint inside the CT |
| `ct_model_storage_path` | `{{ ct_model_storage_mount_path }}` | Existing namespace beneath that mount |
| `ct_model_storage_allowed_fstypes` | `[nfs, nfs4]` | Filesystem types accepted at both the mount and namespace |
| `ct_model_storage_access` | `write` | `read` verifies directory read/traverse access; `write` also probes create, write, rename and removal |
| `ct_model_storage_user` | `infer` | Existing account used by the Ansible access probe |
| `ct_model_storage_service_name` | `""` | Optional `.service` unit receiving the startup guard |
| `ct_model_storage_notify` | `[]` | Optional handlers notified only when the helper or managed drop-in changes |
| `ct_model_storage_helper_path` | `/usr/local/libexec/pve-inference-model-storage-check` | Root-owned local helper |
| `ct_model_storage_systemd_dir` | `/etc/systemd/system` | Local systemd unit directory |

Paths must be canonical absolute non-root paths containing letters, digits,
underscores, dots, slashes and hyphens. Symlinks and parent traversal are
rejected. The namespace may equal the mountpoint. A more specific namespace is
usually preferable so that independent writers do not share one cache.

## Usage

After the `infer` account and CT bind mount exist:

```yaml
- name: Validate the model store before runtime installation
  hosts: ct_targets
  become: true
  roles:
    - role: ktooi.pve_inference.ct_model_storage
      vars:
        ct_model_storage_enabled: true
        ct_model_storage_mount_path: /srv/models
        ct_model_storage_path: /srv/models/huggingface/ct-text
        ct_model_storage_user: infer
        ct_model_storage_access: write
        ct_model_storage_service_name: vllm.service
```

The storage server must already contain `huggingface/ct-text` with appropriate
permissions. The role never creates this namespace or relaxes `root_squash`.
The probe uses the runtime account rather than assuming that CT root can write
an NFS export. Directory access does not prove that every model file is readable;
runtime-specific model validation still applies.

The helper verifies the exact mountpoint and the effective filesystem type of
the namespace. This catches both an empty local directory exposed through a
host bind mount and a local filesystem mounted over a namespace beneath a valid
NFS mount. Configure an additional filesystem type only when that type is
intended; allowing local types also permits corresponding local mounts.

## Service guard and disabling

For a non-empty service name the role manages only
`<service>.d/90-pve-inference-model-storage.conf`. The drop-in declares
`RequiresMountsFor` and runs the same helper through `ExecStartPre`, under the
service's configured `User`. Keep that user aligned with
`ct_model_storage_user`.

The role reloads systemd when its drop-in changes. It never starts or restarts
the service itself. A runtime can supply its restart handler through
`ct_model_storage_notify`; otherwise the new guard takes effect at the next
service start. The deployment invocation validates storage immediately before
installing the guard.

Set `ct_model_storage_enabled: false` and keep the same service name to remove
only this managed drop-in. The helper, other service settings and all model files
remain. If a service is renamed, invoke the disabled role for its old name to
remove that old guard explicitly.

Guest systemd dependencies cannot establish host NFS-before-CT boot ordering.
Manage that order in host infrastructure configuration. A mount/type check does
not prove server identity or continuous availability; an NFS outage can still
block I/O on a hard mount. The probe does not provide distributed locking or
guarantee cache compatibility between runtimes.

`--check` validates declarations and existing local path safety without probing
shared storage or writing its temporary probe file. An actual invocation and
runtime restart are needed to verify the mounted deployment.
