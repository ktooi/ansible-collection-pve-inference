# Support Policy

## Proxmox VE versions
- PVE 9.1.x: **Supported (Main)**
- PVE 8.x: **Supported (Compatibility path)**
- PVE 9.0.x / other 9.x minors: **Best-effort**

## Scope notes
- Primary virtualization target: LXC Container (CT).
- VM-first patterns are outside the main support path.

## Runtime and vendor scope
- Initial supported path: NVIDIA + vLLM.
- Additional runtime/vendor support is added incrementally and tracked in matrix documents.

## Stability guidance
- Prefer PVE 9.1.x for production-critical deployments.
- Use PVE 8.x as a compatibility path when migration is pending.
- Treat non-9.1 9.x minors as best-effort and verify before production rollout.
