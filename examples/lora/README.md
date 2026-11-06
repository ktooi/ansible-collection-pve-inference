# LoRA configuration overlays

Merge [omni.yml](omni.yml) into an existing image CT's host variables. Set the
four `ADAPTER_*` URL/SHA256 environment values on the Ansible controller first.
They are looked up at execution time rather than embedded in this example.
The base model configured by `ct_runtime_vllm_model` must already match the
adapter. Keep the CT's existing version, GPU, CUDA and network settings.

Run the existing `playbooks/runtime_vllm.yml`. No separate deployment script is
required. The role downloads the files and produces
`ct_runtime_vllm_lora_requests['adapter-01']` for request-time use. Refer to
[LoRA deployment](../../docs/lora-deployment.md) for API, ComfyUI and core vLLM
configuration, format requirements and check-mode behavior.
