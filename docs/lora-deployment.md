# Deploy model files and LoRA adapters

Declare file downloads and local adapter aliases in the CT's `host_vars` and run
the existing vLLM runtime playbook. The Collection downloads and verifies files,
validates the local PEFT layout and updates the runtime. It does not start a
second service, change ports/GPUs, upgrade packages or choose offload flags as a
consequence of enabling LoRA. The existing runtime settings still govern these.

## 1. Declare the files and compatible base model

Merge the following into your existing CT host variables. Supply the URL and
SHA256 environment values on the controller before running Ansible. No download
occurs when `ct_model_artifacts` is empty, its default.

```yaml
ct_runtime_vllm_backend: omni
# An already deployed, compatible base model. A normal model ID is also allowed.
ct_runtime_vllm_model: /opt/inference/models/base-model

ct_model_artifacts:
  - name: adapter-01-config
    url: "{{ lookup('ansible.builtin.env', 'ADAPTER_CONFIG_URL') }}"
    dest: /opt/inference/loras/adapter-01/adapter_config.json
    checksum: "sha256:{{ lookup('ansible.builtin.env', 'ADAPTER_CONFIG_SHA256') }}"
  - name: adapter-01-weights
    url: "{{ lookup('ansible.builtin.env', 'ADAPTER_WEIGHTS_URL') }}"
    dest: /opt/inference/loras/adapter-01/adapter_model.safetensors
    checksum: "sha256:{{ lookup('ansible.builtin.env', 'ADAPTER_WEIGHTS_SHA256') }}"

ct_runtime_vllm_lora_adapters:
  - name: adapter-01
    path: /opt/inference/loras/adapter-01
    scale: 0.8
```

The example uses local aliases and environment lookups. Keep real source URLs
and credentials out of committed examples. Download tasks use `no_log` by default;
see the [artifact role](../roles/ct_model_artifacts/README.md) for its privacy scope.

Base-model files can be included in the same artifact list, with one explicit
destination and SHA256 per file. A pre-merged model is deployed as a normal model:
download its complete configuration/tokenizer/weight files and set
`ct_runtime_vllm_model` to that directory, without declaring the same adapter again.

The selected adapter must match the base architecture and the installed runtime.
Registered adapters require a PEFT directory containing `adapter_config.json`
(`peft_type: LORA`, positive `r`) and `adapter_model.safetensors`. The Collection
checks this layout but cannot establish tensor/module compatibility or output
quality without actual inference. Renaming Diffusers, ComfyUI, Kohya or other
checkpoint files does not convert their tensor keys or format. Arbitrary files
can still be downloaded with `ct_model_artifacts` without registering them as
vLLM adapters.

## 2. Apply the existing runtime playbook

From the Collection checkout, using your existing inventory and CT settings:

```bash
ansible-playbook -i inventory/ playbooks/runtime_vllm.yml -l ct-image
```

The `ct_runtime_vllm` role also handles artifact deployment when used in your own
playbook. Changed downloads notify its existing restart handler. A failed
checksum or invalid adapter layout stops deployment before new runtime
configuration is rendered. Check mode skips transfers and checks for files that
are not yet deployed. Preserve any version pins, CUDA settings and GPU selection
from your existing configuration.

## 3. Select the adapter in requests

### Omni image generation

Omni selects compatible adapters per request. Declaring an adapter does not
globally activate it, register a separate `/v1/models` entry, or pass core LLM
LoRA flags. Send the base model and a `lora` object:

```json
{
  "model": "/opt/inference/models/base-model",
  "prompt": "A small red cube on a plain white background",
  "size": "512x512",
  "lora": {
    "name": "adapter-01",
    "local_path": "/opt/inference/loras/adapter-01",
    "scale": 0.8
  }
}
```

POST this body to `/v1/images/generations`. In ComfyUI's official vLLM-Omni
integration, connect **Remote LoRA** with the same name/path/scale to
**Generate Image**. The path is on the inference CT.

After role execution, the non-cached fact
`ct_runtime_vllm_lora_requests['adapter-01']` contains that `lora` object for use
in your own Ansible API tasks. Flush notified handlers before sending requests
from later tasks in the same play. This mapping is deployment metadata, not an
API allowlist or an adapter-unloading mechanism; files are not removed when an
alias is omitted from inventory.

### Core vLLM text generation

For a supported core model, omit Omni-only `scale` and configure:

```yaml
ct_runtime_vllm_backend: core
ct_runtime_vllm_max_lora_rank: 64
ct_runtime_vllm_lora_adapters:
  - name: adapter-01
    path: /opt/inference/loras/adapter-01
```

The role adds `--enable-lora --max-lora-rank 64 --lora-modules
adapter-01=/opt/inference/loras/adapter-01`. Request `model: adapter-01` through
the core completion API. Core aliases use letters, numbers, dots, underscores
and hyphens, starting with a letter, number or underscore; core local paths additionally allow slashes. The configured maximum
rank must be supported by the installed vLLM version and at least the adapter's
rank. The default is 16. An empty adapter list emits none of these flags.
Remove duplicate LoRA options from `ct_runtime_vllm_extra_args` when adopting
the structured settings.

## References and validation scope

- [Omni LoRA format and backends](https://github.com/vllm-project/vllm-omni/blob/c4b31f0c56ab1f4e33f286c5d1c72268b8cf35a5/docs/user_guide/diffusion/lora.md)
- [Omni request-time LoRA API](https://github.com/vllm-project/vllm-omni/blob/c4b31f0c56ab1f4e33f286c5d1c72268b8cf35a5/docs/user_guide/examples/online_serving/text_to_image.md#lora)

Configuration, HTTP download behavior and launcher arguments are tested without
a GPU. An adapter's inference compatibility remains runtime/model-specific.
