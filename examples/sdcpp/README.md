# sd.cpp: P-H3-Image deployment trial

[p-h3-image-w4a8.yml](p-h3-image-w4a8.yml) is a four-CUDA-device profile for the
new `ct_runtime_sdcpp` role. **Actual deployment and GPU inference acceptance are
pending.** Use [the deployment guide](../../docs/sdcpp-deployment.md) before
applying it.

The profile is outside the generic engine role. It selects CUDA architecture 86
for the intended RTX 3090 trial, requires at least four CUDA devices, and uses:

| Component | Revision-pinned file | Bytes |
| --- | --- | ---: |
| Diffusion transformer | `p-h3-image_w4a8.safetensors` | 13,362,068,864 |
| Bundled text encoder, vision tower and connector | `p-h3-image_text_encoder_w4a8.safetensors` | 3,575,536,021 |
| P-H3 image VAE | `p-h3-image_vae_int8_convrot.safetensors` | 3,146,996,440 |

Hashes and sizes were verified against the publisher's raw Git LFS pointers at
revision `44a0fb73f299da1bb715bdb5ff59ce3fd3c6f543` on 2026-11-09 JST.
See [source-metadata.json](source-metadata.json). Verification read metadata;
the model binaries were not downloaded or executed for that check.

The pinned sd.cpp revision supports these packed formats with its normal
patched GGML. Do not enable `SD_USE_UPSTREAM_GGML`. The upstream P-H3 command
example uses INT8 diffusion with BF16 encoder/VAE; the smaller W4A8 combination
here requires its own generation and editing tests.

The profile does not download or run Pruna's prompt upsampler. Provide a detailed
prompt or a separate prompt-expansion stage. Do not assume an arbitrary LLM
produces the same output as the trained upsampler.

Before reuse:

- Confirm the actual CUDA device names and all four GPUs' available memory.
- Provision a compatible CUDA toolkit and set its real `cuda_home`; change
  `ct_runtime_sdcpp_cuda_architectures` when using another GPU generation.
- Review `auto_fit: false` and any per-device budget for the current workload.
- Set a different service identity, paths and port if the defaults already
  belong to another sd.cpp deployment.
- Keep public API access behind the existing authenticated proxy, or use the
  default loopback bind and an SSH tunnel.
- Review the model license and notices for the intended use.

ComfyUI's published roughly 21 GB peak for its W4A8/INT8 execution path is not an
sd.cpp measurement. Four-way layer placement does not imply equal per-GPU
memory, four-fold speedup, or capacity reserved for another LLM.
