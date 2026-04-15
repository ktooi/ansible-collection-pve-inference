# Role: host_nvidia_gpu

## Purpose
Prepare NVIDIA GPU prerequisites on the Proxmox host.

## Usage
```yaml
- hosts: pve_hosts
  become: true
  roles:
    - role: ktooi.pve_inference.host_nvidia_gpu
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `host_nvidia_gpu_packages` | NVIDIA-related packages to install | `['nvidia-driver', 'nvidia-smi']` | Package name list |
| `host_nvidia_gpu_enable_persistenced` | Enable/start `nvidia-persistenced` | `true` | `true` / `false` |

## Notes
The role validates GPU visibility by executing `nvidia-smi -L`.
