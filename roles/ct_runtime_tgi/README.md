# Role: ct_runtime_tgi

## Purpose
Install and run Hugging Face Text Generation Inference (TGI) directly inside CT as a systemd-managed service.

Supported CT distributions: Debian 12/13, Ubuntu 22.04/24.04 LTS, and RHEL/AlmaLinux/Rocky/Oracle Linux 9/10.

## Usage
```yaml
- hosts: ct_targets
  become: true
  roles:
    - role: ktooi.pve_inference.ct_runtime_common
    - role: ktooi.pve_inference.ct_runtime_launcher_common
    - role: ktooi.pve_inference.ct_runtime_tgi
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `ct_runtime_tgi_user` | Service user | `infer` | Existing Linux username |
| `ct_runtime_tgi_group` | Service group | `infer` | Existing Linux group |
| `ct_runtime_tgi_workdir` | Working directory | `/opt/inference` | Absolute path |
| `ct_runtime_tgi_env_file` | Environment file path | `/etc/default/tgi` | Absolute path |
| `ct_runtime_tgi_service_name` | systemd unit name | `tgi.service` | Valid unit name |
| `ct_runtime_tgi_launcher_cmd` | TGI launcher command | `/usr/local/bin/text-generation-launcher` | Executable path |
| `ct_runtime_tgi_packages` | Python packages for TGI launcher | `['text-generation']` | Pip package list |
| `ct_runtime_tgi_bind_host` | API bind host | `{{ ct_runtime_launcher_bind_host | default('0.0.0.0') }}` | IP/host string |
| `ct_runtime_tgi_port` | API port | `{{ ct_runtime_launcher_port | default(8000) }}` | Integer `1..65535` |
| `ct_runtime_tgi_model` | Model identifier | `{{ ct_runtime_launcher_model | default('mistralai/Mistral-7B-Instruct-v0.3', true) }}` | Valid model identifier |
| `ct_runtime_tgi_dtype` | Dtype | `{{ ct_runtime_launcher_dtype | default('auto') }}` | Runtime-supported dtype |
| `ct_runtime_tgi_max_input_length` | Max input tokens | `{{ ct_runtime_launcher_context_length | default(8192) }}` | Integer `>=1` |
| `ct_runtime_tgi_max_total_tokens` | Max total tokens | `{{ ct_runtime_launcher_context_length | default(8192) }}` | Integer `>=1` |
| `ct_runtime_tgi_max_concurrent_requests` | Max concurrent requests | `{{ ct_runtime_launcher_max_num_seqs | default(32) }}` | Integer `>=1` |
| `ct_runtime_tgi_extra_args` | Extra launcher args | `{{ ct_runtime_launcher_extra_args | default('') }}` | String |
