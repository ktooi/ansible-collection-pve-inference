# Collection Specification: `ktooi.pve_inference`

## 1. Objective
Provide an Ansible Collection to provision and operate Proxmox VE container (CT) environments for LLM inference workloads, with clear separation between host setup, CT lifecycle, runtime deployment, and validation.

## 2. Non-objectives
- VM orchestration beyond CT lifecycle.
- Kubernetes-native orchestration features.
- Vendor-specific tuning beyond explicitly implemented role variables.

## 3. Functional specification

### 3.1 Host preparation
- The collection must provide host roles for generic GPU prerequisites and vendor-specific setup.
- Host preparation must be executable independently from CT/runtime deployment.

### 3.2 CT lifecycle
- The collection must provide a CT lifecycle role that can create, update, and delete CT instances through Proxmox API modules.
- Inputs must be variable-driven and documented.

### 3.3 Runtime base
- The collection must provide runtime-agnostic CT preparation (packages, Python environment baseline, shared launcher requirements).

### 3.4 Runtime deployment
- The collection must provide runtime-specific roles for at least:
  - vLLM
  - TGI
  - SGLang
  - Ollama
- Runtime roles must expose variables for model and launch arguments.
- Runtime roles must integrate with systemd service management.

### 3.5 Validation
- The collection must provide a validation role to verify runtime readiness and basic GPU availability from inside CT context.

## 4. Interface specification
- Playbooks under `playbooks/` are reference entry points.
- Role defaults are the primary configuration contract.
- Role READMEs define variable semantics and expected value formats.

## 5. Quality requirements
- Idempotent execution is required.
- Syntax check must pass for provided test playbooks.
- Documentation and defaults must stay consistent with task behavior.

## 6. Compatibility expectations
- Target platform is Proxmox VE + Linux guests supported by included variable maps.
- Unsupported combinations may exist; unsupported status must be explicit in docs.

## 7. Change control
- Breaking variable contract changes require:
  1. README update
  2. Migration guidance
  3. ADR update or new ADR when architectural intent changes
