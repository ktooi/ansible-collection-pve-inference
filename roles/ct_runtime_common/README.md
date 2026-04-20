# Role: ct_runtime_common

## Purpose
Prepare shared runtime foundation inside CT.

Supported CT distributions: Debian 12/13, Ubuntu 22.04/24.04 LTS, and RHEL/AlmaLinux/Rocky/Oracle Linux 9/10.

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
| `ct_runtime_common_apt_cache_valid_time` | Debian apt cache validity (seconds) | `3600` | Integer `>=0` |


## Troubleshooting

If Debian package install fails with `404 Not Found`, cached apt metadata is usually stale.
This role now refreshes apt cache before install and retries once with a forced refresh.
You can lower `ct_runtime_common_apt_cache_valid_time` if your mirror changes frequently.
