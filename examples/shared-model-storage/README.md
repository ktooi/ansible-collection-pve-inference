# Shared model storage examples

Use the [shared model storage guide](../../docs/shared-model-storage.md) for the
host NFS mount, new/existing CT bind-mount procedure and runtime-specific vars.
The feature is optional; real NFS/runtime acceptance is pending.

For the existing P-H3 example, copy the guide's complete sd.cpp storage overlay
to `shared-model-storage.yml` in your playbook project. Provision the NAS
namespace and CT mount first, then apply the pinned model profile before the
overlay:

```bash
ansible-playbook -i /path/to/inventory.ini \
  ktooi.pve_inference.runtime_sdcpp \
  --limit ct-sdcpp \
  -e @examples/sdcpp/p-h3-image-w4a8.yml \
  -e @/path/to/shared-model-storage.yml
```

The first extra-vars path is relative to the collection checkout. Adapt paths
when the example is copied into another project. Preserve the complete three
component mappings and the profile's checksum-pinned artifact list. The overlay
changes model destinations and artifact permissions, while source/build caches
remain local.

For vLLM core/Omni, TGI, SGLang and Ollama, use their corresponding examples in
the guide. Select a separate prepared namespace for each intended writer unless
you have explicitly tested a shared-writer identity/permission policy.

Changing variables does not migrate existing weights, prepare NAS ownership,
add a mount to an already existing CT or certify multi-client locking. Verify
the actual backing filesystem and the runtime account's access before applying
the runtime.
