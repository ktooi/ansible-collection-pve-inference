# ADR-002: vLLM modality backends

- Status: Accepted
- Date: 2026-11-03

## Context

Core vLLM serves supported transcription and diarization-capable ASR models.
Diffusion image/video generation uses the separate vLLM-Omni extension, whose
CLI and package compatibility differ from core language-model serving.

## Decision

Keep CT runtime deployment in `ct_runtime_vllm`, with an explicit `core` (default)
or `omni` backend. Install vLLM, optional audio extras, Omni and model-specific
packages in a single pip transaction so the resolver checks their requirements
together. Preserve version pins and make upgrading an explicit `latest` option.

For Omni, pass model, host, port and `--omni`, plus administrator-provided extra
arguments. Do not automatically pass core LLM scheduling, KV cache or parser
options to diffusion models. Retain the existing core launch configuration.

## Consequences

Existing configurations keep their core behavior. One service serves one model;
concurrent modalities require separately provisioned CTs/services and GPU capacity.
Model/API support must be checked against the selected release. Local template
and syntax checks do not establish GPU inference readiness.
