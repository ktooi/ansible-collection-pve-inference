# ADR-006: Native sd.cpp runtime within the CT inference collection

- Status: Proposed — implementation direction approved; deployment validation pending
- Date: 2026-11-09

## Context

P-H3-Image can use stable-diffusion.cpp as an image API backend. Its C++/CUDA
build, model components and GPU placement differ from the Python-based vLLM
family. The collection already separates PVE host preparation, CT lifecycle and
runtime deployment (ADR-001), and keeps core/Omni together in the vLLM role
(ADR-002).

The user approved this implementation direction on 2026-11-09, with final
acceptance explicitly deferred until actual deployment tests.

## Proposed decision

1. Add an independent `ct_runtime_sdcpp` role and `runtime_sdcpp` playbook within
   this collection. Do not add sd.cpp as a vLLM backend or split roles by image,
   text or audio modality.
2. Keep host driver changes, GPU device exposure and CT lifecycle in their
   existing roles. The runtime entry point operates on an already prepared CT.
3. Make common runtime venv creation optional, retaining the existing enabled
   default. sd.cpp reuses account/directory preparation without a runtime venv.
4. Build a commit-pinned native `sd-server` with patched GGML and an explicit CUDA
   toolkit. Give it independent install, configuration, service and port settings.
5. Reuse checksum-pinned artifact delivery (ADR-005). Keep model-specific
   component revisions, precision and sampling/placement settings in examples or
   caller variables, outside the generic engine role.
6. Keep sd.cpp backend, split and memory options distinct from LLM context,
   KV-cache and tensor-parallel settings. Model readiness and actual inference
   are separate checks.
7. Consider a generic inference collection only when non-PVE consumers or
   independent release ownership justify it. Such a collection must not depend
   back on PVE-specific runtime helpers.

## Consequences

Existing core/Omni behavior and common-role callers retain their defaults.
Installing this collection does not run every runtime role. Separating services
or collections does not reserve physical GPU memory.

Source builds need a compatible host driver, guest CUDA toolkit, compiler and
capacity for source/build artifacts. These remain explicit deployment inputs.
The initial sd.cpp OS path is Debian/Ubuntu; a declared OS path is not a record
of successful GPU deployment.

The P-H3 example uses a recently added upstream implementation and packed
W4A8/INT8 components. Upstream format support is not an inference benchmark.
The example neither stops other GPU services nor claims equal VRAM on all GPUs.

## Acceptance before changing status

Keep this ADR Proposed until the [deployment acceptance](../docs/sdcpp-deployment.md#acceptance-record)
records the actual host/CT versions, pinned build and model files, successful
generation and reference-image editing, per-GPU peak VRAM, LLM co-residency,
repeat-run behavior and recovery. Record any required design changes first.

Repository unit/template/Ansible-fixture checks support review of the
implementation. They do not establish CUDA build, P-H3 quality, GPU sharing or
deployment readiness on the user's target.

## References

- [Collection boundaries](adr-001-collection-boundary-and-contracts.md)
- [vLLM modality backends](adr-002-vllm-modality-backends.md)
- [Artifact delivery](adr-005-model-artifacts-and-lora.md)
- [Pinned sd.cpp P-H3 guide](https://github.com/leejet/stable-diffusion.cpp/blob/fc350be2ceeeb859bcc201ac435591ed7d46821d/docs/p_h3_image.md)
