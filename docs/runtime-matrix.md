# Runtime Support Matrix

| PVE    | Vendor | Runtime | Status      | Notes |
|--------|--------|---------|-------------|-------|
| 9.1.x  | NVIDIA | vLLM    | Supported   | Main production path |
| 8.x    | NVIDIA | vLLM    | Supported   | Compatibility path |
| 9.0.x  | NVIDIA | vLLM    | Best-effort | Validate before production use |
| 9.1.x  | NVIDIA | SGLang  | Planned     | Role available; validation in progress |
| 9.1.x  | NVIDIA | TGI     | Planned     | Role available; validation in progress |
| 9.1.x  | NVIDIA | Ollama  | Planned     | Role available; validation in progress |
| 9.1.x  | AMD    | vLLM    | Planned     | Future extension |
| 9.2.x  | NVIDIA | stable-diffusion.cpp | Deployment pending | Native role and pinned P-H3 example; proposed RTX 3090 x4 trial |

The sd.cpp role has an initial Debian 12/13 and Ubuntu 22.04/24.04 guest package
path. These are implementation targets, not completed GPU deployment results.
PVE 9.2 remains subject to the collection's existing best-effort host policy.
Keep [ADR-006](../adr/adr-006-sdcpp-runtime.md) Proposed until the actual
[deployment acceptance record](sdcpp-deployment.md#acceptance-record) is reviewed.
Syntax/template/local-fixture checks do not establish model inference or LLM
co-residency, and support status from another runtime does not transfer to sd.cpp.
