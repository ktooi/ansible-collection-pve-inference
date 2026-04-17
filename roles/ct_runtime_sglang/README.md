# Role: ct_runtime_sglang

## Purpose
Install and run SGLang directly inside CT as a systemd-managed service.

Supported CT distributions: Debian 12/13, Ubuntu 22.04/24.04 LTS, and RHEL/AlmaLinux/Rocky/Oracle Linux 9/10.

## Usage
```yaml
- hosts: ct_targets
  become: true
  roles:
    - role: ktooi.pve_inference.ct_runtime_common
    - role: ktooi.pve_inference.ct_runtime_launcher_common
    - role: ktooi.pve_inference.ct_runtime_sglang
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `ct_runtime_sglang_user` | Service user | `infer` | Existing Linux username |
| `ct_runtime_sglang_group` | Service group | `infer` | Existing Linux group |
| `ct_runtime_sglang_venv` | Python virtualenv path | `/opt/inference/venv` | Absolute path |
| `ct_runtime_sglang_workdir` | Working directory | `/opt/inference` | Absolute path |
| `ct_runtime_sglang_env_file` | Environment file path | `/etc/default/sglang` | Absolute path |
| `ct_runtime_sglang_service_name` | systemd unit name | `sglang.service` | Valid unit name |
| `ct_runtime_sglang_bind_host` | API bind host | `{{ ct_runtime_launcher_bind_host | default('0.0.0.0') }}` | IP/host string |
| `ct_runtime_sglang_port` | API port | `{{ ct_runtime_launcher_port | default(8000) }}` | Integer `1..65535` |
| `ct_runtime_sglang_model` | Model identifier/path | `{{ ct_runtime_launcher_model | default('Qwen/Qwen2.5-7B-Instruct', true) }}` | Valid model identifier/path |
| `ct_runtime_sglang_tensor_parallel_size` | Tensor parallel size | `{{ ct_runtime_launcher_tensor_parallel_size | default(1) }}` | Integer `>=1` |
| `ct_runtime_sglang_context_length` | Context length | `{{ ct_runtime_launcher_context_length | default(8192) }}` | Integer `>=1` |
| `ct_runtime_sglang_dtype` | Dtype | `{{ ct_runtime_launcher_dtype | default('auto') }}` | Runtime-supported dtype |
| `ct_runtime_sglang_extra_args` | Extra launcher args | `{{ ct_runtime_launcher_extra_args | default('') }}` | String |
| `ct_runtime_sglang_version` | Optional pinned package version | `""` | Empty or version string |
