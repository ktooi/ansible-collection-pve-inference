# Role: host_nvidia_gpu

## Purpose
Prepare NVIDIA GPU prerequisites on the Proxmox host, including kernel headers/DKMS checks, driver installation, module loading, and persistence daemon startup.

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
| `host_nvidia_gpu_prereq_packages` | Build and DKMS prerequisite packages | `['build-essential','dkms','mokutil']` | Package list |
| `host_nvidia_gpu_header_packages` | Preferred/fallback header packages | `['pve-headers-{{ ansible_kernel }}','pve-headers']` | Package list (length 2 expected) |
| `host_nvidia_gpu_packages` | NVIDIA driver stack packages | `['nvidia-driver','nvidia-kernel-dkms','nvidia-smi','nvidia-persistenced','nvidia-modprobe','firmware-misc-nonfree']` | Package list |
| `host_nvidia_gpu_modules` | Modules to load | `['nvidia','nvidia_uvm','nvidia_modeset','nvidia_drm']` | Module name list |
| `host_nvidia_gpu_enable_persistenced` | Enable/start `nvidia-persistenced` | `true` | `true` / `false` |
| `host_nvidia_gpu_require_pve_kernel` | Enforce running `*-pve` kernel precondition | `true` | `true` / `false` |
| `host_nvidia_gpu_require_nvidia_devices` | Enforce `/dev/nvidia*` existence check | `true` | `true` / `false` |

## Notes
- This role validates implicit prerequisites (Debian family host, Proxmox kernel, NVIDIA device nodes) and fails early if they are not met.
- If Secure Boot is enabled, ensure DKMS MOK enrollment is completed so NVIDIA modules can be loaded.
