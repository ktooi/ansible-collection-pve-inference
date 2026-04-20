# Role: host_gpu_common

## Purpose
Common host prerequisites shared across GPU vendors.

## Usage
```yaml
- hosts: pve_hosts
  become: true
  roles:
    - role: ktooi.pve_inference.host_gpu_common
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `host_gpu_common_packages` | Common host packages | `['pciutils', 'lshw', 'curl']` | Package name list |
| `host_gpu_common_sysctl` | Common sysctl settings map | `{}` | Dict `{ key: value }` |
| `host_gpu_common_limits` | Reserved for common limits config | `[]` | List |

## Notes
This role is intentionally vendor-neutral. Use together with vendor roles (`host_nvidia_gpu`, `host_amd_gpu`).
