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
| `host_nvidia_gpu_header_packages` | Exact header package for running kernel | `['pve-headers-{{ ansible_kernel }}']` | Package list |
| `host_nvidia_gpu_packages` | NVIDIA driver stack packages | `['nvidia-driver','nvidia-kernel-dkms','nvidia-smi','nvidia-persistenced','nvidia-modprobe']` | Package list |
| `host_nvidia_gpu_modules_standard` | Standard NVIDIA module names | `['nvidia','nvidia_uvm','nvidia_modeset','nvidia_drm']` | Module name list |
| `host_nvidia_gpu_modules_current` | Debian alias-based NVIDIA module names | `['nvidia-current','nvidia-current-uvm','nvidia-current-modeset','nvidia-current-drm']` | Module name list |
| `host_nvidia_gpu_enable_persistenced` | Enable/start `nvidia-persistenced` | `true` | `true` / `false` |
| `host_nvidia_gpu_require_pve_kernel` | Enforce running `*-pve` kernel precondition | `true` | `true` / `false` |
| `host_nvidia_gpu_require_nvidia_devices` | Enforce `/dev/nvidia*` existence check | `true` | `true` / `false` |
| `host_nvidia_gpu_block_proxmox_removal` | Abort if apt plan would remove `proxmox-ve` | `true` | `true` / `false` |
| `host_nvidia_gpu_require_exact_headers` | Require exact running-kernel headers | `true` | `true` / `false` |

## Notes
- This role validates implicit prerequisites (Debian family host, Proxmox kernel, exact headers, NVIDIA device nodes) and fails early if they are not met.
- The role simulates apt install and aborts when the plan would remove `proxmox-ve`.
- The role runs `dkms autoinstall -k {{ ansible_kernel }}`, detects whether the host uses `nvidia-*` or `nvidia-current-*` module naming, and loads the matching module set.
- If Secure Boot is enabled, ensure DKMS MOK enrollment is completed so NVIDIA modules can be loaded.
