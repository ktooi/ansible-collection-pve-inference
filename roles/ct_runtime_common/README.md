# Role: ct_runtime_common

## Purpose
Prepare shared runtime foundation inside CT.

## Usage
```yaml
- hosts: ct_targets
  become: true
  roles:
    - role: ktooi.pve_inference.ct_runtime_common
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `ct_runtime_common_user` | Runtime OS user | `infer` | Valid Linux username |
| `ct_runtime_common_group` | Runtime OS group | `infer` | Valid Linux group |
| `ct_runtime_common_home` | Runtime user home | `/opt/inference` | Absolute path |
| `ct_runtime_common_venv` | Python virtualenv path | `/opt/inference/venv` | Absolute path |
| `ct_runtime_common_packages` | Base packages in CT | `['python3','python3-venv','python3-pip','curl','git']` | Package name list |
| `ct_runtime_common_directories` | Directories to create | `['/opt/inference','/opt/inference/bin','/var/log/inference','/var/cache/inference']` | Absolute path list |
