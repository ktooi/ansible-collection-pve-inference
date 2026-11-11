# ADR-007: Optional shared model storage across runtimes

- Status: Proposed — real NFS and runtime acceptance pending
- Date: 2026-11-11

## Context

Model downloads can exceed a CT's root filesystem capacity and are expensive to
repeat after CT recreation. Explicit artifact destinations already support
arbitrary paths, while runtime model caches use different variables. Pointing a
path at an unmounted directory can silently consume local storage. NFS also
introduces numeric identity, root-squash and multi-client update constraints.

The requirement covers image, language and other inference workloads. Storage
availability and ownership are independent of a model format or runtime.

## Proposed decision

1. Add optional `ct_model_storage` preparation/validation shared by the runtime
   integrations. Keep it disabled by default and retain all local defaults.
2. Consume an existing CT-visible mount and precreated namespace. Host mount
   management remains a host/infrastructure responsibility; CT bind mounts
   remain a CT lifecycle responsibility. Do not grant guest mount privileges or
   change AppArmor/privileged-container policy.
3. Require an exact mount, an allowed backing filesystem type and access by the
   runtime user before deployment. Repeat the check with an `ExecStartPre`
   service guard. Mount-point existence alone cannot distinguish NFS from a
   bind mount of an unmounted host-local directory. Guest `RequiresMountsFor`
   cannot establish the host's mount and does not monitor NAS health.
4. Keep model component paths, artifact destinations and cache locations
   explicit. The selected namespace is guarded; the role does not relocate
   existing files or enforce containment on every runtime path. Callers can mix
   shared and local components deliberately.
5. Add model-only Hub-cache settings for vLLM, TGI and SGLang without relocating
   `HF_HOME` or credentials. Preserve legacy vLLM cache behavior when the new
   setting is unset and reject conflicting declarations. Keep build/compile
   caches, environments, secrets and transient state local.
6. Allow artifact acquisition under an explicit writer identity without
   owner/group/mode changes, and allow Ollama to consume a server-prepared model
   directory. Do not recursively chown a shared tree or disable root squashing.
7. Begin with a controlled writer per namespace and immutable/versioned model
   destinations. Atomic downloads do not establish distributed serialization.
   Do not add a distributed lock, cache garbage collector, migration facility
   or local staging cache in this change.

## Consequences

The same optional contract applies across runtimes without making image roles
responsible for host storage. CT recreation can reuse externally stored weights,
but NAS provisioning, backup and mount ordering remain operator responsibilities.
Bind-mounted data is not included in `vzdump`.

NFS root squashing and unprivileged CT mappings require a deliberate numeric
identity policy. A startup check reduces accidental local fallback but cannot
guarantee continued server availability. Hard mounts can block I/O during an
outage; cold loads and parallel starts depend on network/storage bandwidth.
Neither shared storage nor local staging reduces a model's GPU memory needs.

## Acceptance before changing status

Keep this decision Proposed until actual NFS downloads, inference, repeat-run
behavior, startup with unavailable storage, host/CT restart recovery and
identity/permission behavior are recorded. Confirm no unwanted local fallback
writes. Verify concurrency only for the actual client/server and library
versions in use; do not infer it from a local fixture. Follow the
[deployment guide](../docs/shared-model-storage.md#target-acceptance).

## References

- [Collection responsibility boundaries](adr-001-collection-boundary-and-contracts.md)
- [Checksum-pinned model delivery](adr-005-model-artifacts-and-lora.md)
- [Proxmox CT bind mounts](https://github.com/proxmox/pve-docs/blob/master/pct.adoc)
- [Hugging Face environment variables](https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables)
- [Hugging Face concurrent-download fix](https://github.com/huggingface/huggingface_hub/pull/4306)
- [NFS export permissions](https://man7.org/linux/man-pages/man5/exports.5.html)
- [NFS recovery semantics](https://man7.org/linux/man-pages/man5/nfs.5.html)
- [systemd unit dependencies](https://www.freedesktop.org/software/systemd/man/latest/systemd.unit)
