# Role: ct_validate

## Purpose
Run post-deployment checks for GPU visibility, service presence, and API health.

## Usage
```yaml
- hosts: ct_targets
  become: true
  roles:
    - role: ktooi.pve_inference.ct_validate
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `ct_validate_check_gpu_command` | Command used to check GPU visibility | `nvidia-smi -L` | Executable command string |
| `ct_validate_check_api_url` | Runtime API health URL | `http://127.0.0.1:8000/health` | Valid URL |
| `ct_validate_check_service_name` | Service to validate | `vllm.service` | Existing service unit |
| `ct_validate_check_service_enabled` | Reserved toggle for future strict checks | `true` | `true` / `false` |
