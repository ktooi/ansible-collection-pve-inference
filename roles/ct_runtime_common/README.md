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
| `ct_runtime_common_install_nvidia_smi` | Try to install `nvidia-smi` package in CT | `true` | `true` / `false` |
| `ct_runtime_common_nvidia_smi_packages` | `nvidia-smi` package candidates in CT | distro-dependent (`['nvidia-smi']` on Debian/Ubuntu) | Package name list |
| `ct_runtime_common_fail_on_nvidia_smi_install` | Fail when `nvidia-smi` package installation fails (effective `true` when `ct_runtime_common_nvidia_power_limit_watts` is set) | `false` | `true` / `false` |
| `ct_runtime_common_nvidia_power_limit_watts` | GPU power limit (watts) applied at CT boot via `nvidia-smi -pl` | `""` (disabled) | Empty or integer string |
| `ct_runtime_common_nvidia_power_limit_service_name` | systemd unit name for CT power-limit apply job | `ct-nvidia-power-limit.service` | Valid unit name |
| `ct_runtime_common_nvidia_power_limit_script_path` | Path to generated power-limit helper script | `/usr/local/sbin/ct-apply-nvidia-power-limit.sh` | Absolute path |
| `ct_runtime_common_directories` | Directories to create | `['/opt/inference','/opt/inference/bin','/var/log/inference','/var/cache/inference']` | Absolute path list |
| `ct_runtime_common_apt_cache_valid_time` | Debian apt cache validity (seconds) | `3600` | Integer `>=0` |


## Troubleshooting

If Debian package install fails with `404 Not Found`, cached apt metadata is usually stale.
This role now refreshes apt cache before install and retries once with a forced refresh.
You can lower `ct_runtime_common_apt_cache_valid_time` if your mirror changes frequently.

When `ct_runtime_common_nvidia_power_limit_watts` is set, this role treats `nvidia-smi` install as required, validates `/usr/bin/nvidia-smi`, and installs/enables a oneshot systemd service in CT that applies `nvidia-smi -pm 1` and `nvidia-smi -pl <watts>` at boot.
