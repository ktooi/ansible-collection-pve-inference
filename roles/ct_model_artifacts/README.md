# Role: ct_model_artifacts

Download model configuration, base weights and LoRA files to explicit CT-local
paths using `ansible.builtin.get_url`. Every file requires a pinned SHA256.
Existing files with matching checksums are reused; replacements use a temporary
file in the destination directory and are installed after checksum verification.

`ct_runtime_vllm` invokes this role automatically before configuring its service.
Other runtimes can include it explicitly after their runtime user exists.

## Variables

| Variable | Default | Meaning |
|---|---|---|
| `ct_model_artifacts` | `[]` | List of files described below |
| `ct_model_artifacts_owner` / `ct_model_artifacts_group` | `infer` | Existing CT user/group; supplied by the vLLM role when included there |
| `ct_model_artifacts_directory_mode` | `'0755'` | Parent directory mode |
| `ct_model_artifacts_file_mode` | `'0644'` | Downloaded file mode |
| `ct_model_artifacts_timeout` | `60` | HTTP socket timeout in seconds, not a total transfer deadline |
| `ct_model_artifacts_validate_certs` | `true` | Verify HTTPS certificates |
| `ct_model_artifacts_no_log` | `true` | Hide source URLs, authentication headers and download results in Ansible output |
| `ct_model_artifacts_notify` | `[]` | Handler names notified when a download changes; vLLM supplies its restart handler |

Each file has `url`, `dest`, `checksum`, optional `name` (a local alias), and
optional `headers`. `dest` must be an absolute file path, and destinations must
be unique. Existing directories/symlinks cannot be used as file destinations.
Only HTTP(S) sources and literal `sha256:<64 hex digits>` checksums are accepted.
Authorization headers are not forwarded across redirects.

```yaml
ct_model_artifacts:
  - name: adapter-01-config
    url: "{{ lookup('ansible.builtin.env', 'ADAPTER_CONFIG_URL') }}"
    dest: /opt/inference/loras/adapter-01/adapter_config.json
    checksum: "sha256:{{ lookup('ansible.builtin.env', 'ADAPTER_CONFIG_SHA256') }}"
  - name: adapter-01-weights
    url: "{{ lookup('ansible.builtin.env', 'ADAPTER_WEIGHTS_URL') }}"
    dest: /opt/inference/loras/adapter-01/adapter_model.safetensors
    checksum: "sha256:{{ lookup('ansible.builtin.env', 'ADAPTER_WEIGHTS_SHA256') }}"
```

Use revision-pinned URLs and hashes from a trusted release. Private sources can
use a Vault-backed `headers: {Authorization: 'Bearer ...'}` value. Environment
lookups keep source identifiers out of the inventory examples. `no_log` masks
Ansible output; it does not encrypt inventory, change Ansible transport storage,
or remove metadata embedded in downloaded files. This role does not create a
Hugging Face repository-named cache.

Check mode validates declarations and reports directory changes without making
HTTP requests. It cannot validate files that have not been downloaded yet.
Omitting a previously managed file does not delete it. No checkpoint conversion,
LoRA merging, archive extraction, repository snapshot discovery or model-license
selection is performed.

Check the backing storage pool's physical capacity before deployment. CT `df`
alone cannot measure thin-pool exhaustion. See
[storage troubleshooting](../../docs/troubleshooting-ct-storage.md).

For runtime integration and request examples, see
[LoRA deployment](../../docs/lora-deployment.md).
