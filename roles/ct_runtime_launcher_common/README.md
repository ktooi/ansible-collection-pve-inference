# Role: ct_runtime_launcher_common

## Purpose
Provide shared launcher-level variables (model/context/parallelism/etc.) that can be consumed across runtime roles.

Supported CT distributions: Debian 12/13, Ubuntu 22.04/24.04 LTS, and RHEL/AlmaLinux/Rocky/Oracle Linux 9/10.

This role does **not** remove runtime-specific variables. Runtime variables such as `ct_runtime_vllm_model` remain valid and can still be used directly.

## Usage
```yaml
- hosts: ct_targets
  become: true
  roles:
    - role: ktooi.pve_inference.ct_runtime_common
    - role: ktooi.pve_inference.ct_runtime_launcher_common
    - role: ktooi.pve_inference.ct_runtime_vllm
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `ct_runtime_launcher_bind_host` | API bind host | `0.0.0.0` | IP/host string |
| `ct_runtime_launcher_port` | API port | `8000` | Integer `1..65535` |
| `ct_runtime_launcher_model` | Shared model identifier | `""` | Empty or valid model identifier |
| `ct_runtime_launcher_served_model_name` | Shared served model alias | `""` | Empty or string |
| `ct_runtime_launcher_context_length` | Shared context length | `8192` | Integer `>=1` |
| `ct_runtime_launcher_tensor_parallel_size` | Shared tensor parallel size | `1` | Integer `>=1` |
| `ct_runtime_launcher_pipeline_parallel_size` | Shared pipeline parallel size | `1` | Integer `>=1` |
| `ct_runtime_launcher_gpu_memory_utilization` | Shared memory utilization | `0.9` | Float `0.1..1.0` |
| `ct_runtime_launcher_dtype` | Shared dtype | `auto` | Runtime-supported dtype |
| `ct_runtime_launcher_kv_cache_dtype` | Shared KV cache dtype | `auto` | Runtime-supported dtype |
| `ct_runtime_launcher_max_num_seqs` | Shared max num seqs | `32` | Integer `>=1` |
| `ct_runtime_launcher_max_num_batched_tokens` | Shared max batched tokens | `4096` | Integer `>=1` |
| `ct_runtime_launcher_tool_call_parser` | Shared tool parser | `""` | Empty or parser name |
| `ct_runtime_launcher_reasoning_parser` | Shared reasoning parser | `""` | Empty or parser name |
| `ct_runtime_launcher_extra_args` | Shared extra args | `""` | String |

## Output
The role sets a host fact dictionary `ct_runtime_launcher_effective` for downstream roles.
