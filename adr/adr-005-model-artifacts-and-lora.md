# ADR-005: Model artifacts and LoRA deployment

- Status: Accepted
- Date: 2026-11-06

## Context

Runtime installation does not deploy local adapter assets. Serving references to
missing files or assuming all image checkpoints share core vLLM's LoRA flags
produces incomplete deployments and backend-incompatible commands.

## Decision

Keep CT-local file delivery in `ct_model_artifacts`, independent of host GPU and
CT lifecycle roles. Use native checksum-pinned, atomic HTTP downloads and explicit
destinations. The vLLM role includes this role with its runtime user and restart
handler. Other runtimes can include it explicitly. Defaults deploy no assets.

Use `ct_runtime_vllm_lora_adapters` for local PEFT directory declarations. Core
vLLM receives named LoRA module flags. Omni keeps request-time adapter selection
and exposes non-cached request objects for clients; it receives no core LoRA
flags. Validate local layout before rendering new service configuration.

## Consequences

Existing runtime configuration remains unchanged when both lists are empty.
An administrator supplies source URLs, trusted checksums, a matching base model
and supported runtime versions. This feature performs no format conversion,
automatic model merging, snapshot discovery, GPU/offload selection or adapter
removal. Actual inference remains the compatibility check.
