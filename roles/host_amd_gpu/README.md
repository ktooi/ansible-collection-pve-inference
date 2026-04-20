# Role: host_amd_gpu

## Purpose
Placeholder role for future AMD GPU enablement on the Proxmox host.

## Usage
```yaml
- hosts: pve_hosts
  become: true
  roles:
    - role: ktooi.pve_inference.host_amd_gpu
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `host_amd_gpu_enabled` | Toggle placeholder behavior | `false` | `true` / `false` |

## Notes
Current implementation is a scaffold and prints a guidance message.
