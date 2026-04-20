# AGENTS.md

## Purpose
This file defines how AI agents should generate and modify code in this collection with consistent quality.

## Scope
- Applies to the entire repository.
- If a deeper directory contains another `AGENTS.md`, the deeper file takes precedence for that subtree.

## Output quality rules
1. Keep responses and generated files concise, explicit, and non-repetitive.
2. Prefer small, reviewable changes over broad rewrites.
3. Preserve backward compatibility unless a breaking change is explicitly requested.
4. Do not invent unsupported features or module parameters.
5. For any behavior change, update related documentation in the same change.

## Collection architecture constraints
- This is an **Ansible Collection** focused on Proxmox VE CT-based inference environments.
- Responsibility split:
  - Host-side GPU and driver preparation: `host_*` roles.
  - CT lifecycle: `ct_instance` role.
  - Runtime base preparation: `ct_runtime_common` and `ct_runtime_launcher_common`.
  - Runtime-specific deployment: `ct_runtime_vllm`, `ct_runtime_tgi`, `ct_runtime_sglang`, `ct_runtime_ollama`.
  - Validation: `ct_validate`.
- Keep this boundary clear; avoid mixing host and CT concerns in one role.

## Implementation rules
- Use FQCN for modules (for example `ansible.builtin.*`, `community.general.*`).
- Keep defaults in `defaults/main.yml`; avoid hardcoding environment-specific values in tasks.
- Place OS-family or distribution switches in `vars/` or dedicated variable tasks, not scattered throughout task files.
- Use idempotent tasks and avoid shell commands when native modules are available.
- Keep handlers minimal and trigger them only on actual changes.

## Documentation rules
- Any new role must include:
  - `README.md` (purpose, variables, basic usage)
  - `defaults/main.yml`
  - `meta/main.yml`
  - `tasks/main.yml`
- Keep docs aligned with implemented behavior; do not document aspirational behavior as if implemented.

## Validation expectations
- Run at least syntax-level checks before finalizing changes.
- If full runtime validation is not possible, state limitations clearly and avoid false claims.

## ADR policy
- Record cross-cutting or long-lived decisions under `adr/`.
- Do not use ADRs for trivial refactors.
- If implementation contradicts an ADR, either:
  - update implementation to match ADR, or
  - add a superseding ADR with rationale.
