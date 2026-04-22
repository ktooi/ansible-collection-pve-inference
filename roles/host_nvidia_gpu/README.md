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
| `host_nvidia_gpu_apt_default_release` | APT target release (`-t`) for NVIDIA-related installs | `""` | Empty or apt suite (e.g. `trixie-backports`) |
| `host_nvidia_gpu_require_apt_default_release` | Fail if configured target release is unavailable in apt sources | `false` | `true` / `false` |
| `host_nvidia_gpu_auto_select_open_kernel_module` | Prefer `nvidia-open-kernel-dkms` when available | `true` | `true` / `false` |
| `host_nvidia_gpu_min_driver_major_for_kernel_6_12_plus` | Minimum accepted `nvidia-driver` major for kernel `>=6.12` | `550` | Integer |
| `host_nvidia_gpu_min_installed_driver_major` | Enforce minimum installed driver major after install (`0` disables) | `0` | Integer |
| `host_nvidia_gpu_modules_standard` | Standard NVIDIA module names | `['nvidia','nvidia_uvm','nvidia_modeset','nvidia_drm']` | Module name list |
| `host_nvidia_gpu_modules_current` | Debian alias-based NVIDIA module names | `['nvidia-current','nvidia-current-uvm','nvidia-current-modeset','nvidia-current-drm']` | Module name list |
| `host_nvidia_gpu_enable_persistenced` | Enable/start `nvidia-persistenced` | `true` | `true` / `false` |
| `host_nvidia_gpu_ensure_uvm_device_service` | Deploy/enable a boot-time oneshot service that runs `nvidia-modprobe -u -c=0` | `true` | `true` / `false` |
| `host_nvidia_gpu_uvm_device_service_name` | systemd unit name for UVM device recreation | `nvidia-uvm-devices.service` | Valid unit name |
| `host_nvidia_gpu_power_limit_watts` | GPU power limit (watts) applied on host boot via `nvidia-smi -pl` | `""` (disabled) | Empty or integer string |
| `host_nvidia_gpu_power_limit_service_name` | systemd unit name for host power-limit apply job | `nvidia-power-limit.service` | Valid unit name |
| `host_nvidia_gpu_power_limit_script_path` | Path to generated host power-limit helper script | `/usr/local/sbin/host-apply-nvidia-power-limit.sh` | Absolute path |
| `host_nvidia_gpu_require_pve_kernel` | Enforce running `*-pve` kernel precondition | `true` | `true` / `false` |
| `host_nvidia_gpu_require_nvidia_devices` | Enforce `/dev/nvidia*` existence check | `true` | `true` / `false` |
| `host_nvidia_gpu_block_proxmox_removal` | Abort if apt plan would remove `proxmox-ve` | `true` | `true` / `false` |
| `host_nvidia_gpu_require_exact_headers` | Require exact running-kernel headers | `true` | `true` / `false` |

## Notes
- This role validates implicit prerequisites (Debian family host, Proxmox kernel, exact headers, NVIDIA device nodes) and fails early if they are not met.
- The role simulates apt install and aborts when the plan would remove `proxmox-ve`.
- When `host_nvidia_gpu_apt_default_release` is set but unavailable in apt sources, the role warns and falls back to normal apt behavior unless strict mode is enabled.
- For modern PVE kernel lines (`>=6.12`), the role validates that apt provides a sufficiently new `nvidia-driver` candidate and fails early if not.
- When available, the role prefers `nvidia-open-kernel-dkms` over `nvidia-kernel-dkms` by default (configurable).
- The role runs `dkms autoinstall -k {{ ansible_kernel }}`, then checks running-kernel readiness via DKMS status first; module-file fallback is used only when DKMS reports no NVIDIA kernel entries.
- If DKMS only exists for older kernels (for example after a major PVE kernel jump), the role now fails early with guidance about repo/driver compatibility and reboot requirements.
- The role attempts both `nvidia-*` and `nvidia-current-*` module sets when needed, and fails with DKMS/modprobe diagnostics only if both paths fail.
- If Secure Boot is enabled, ensure DKMS MOK enrollment is completed so NVIDIA modules can be loaded.

- The role also validates critical host CUDA nodes (`/dev/nvidiactl`, `/dev/nvidia-uvm`) are character devices before CT passthrough use.
- By default, this role also deploys a host boot-time oneshot unit (`nvidia-uvm-devices.service`) so `/dev/nvidia-uvm*` is recreated automatically after reboot.
- When `host_nvidia_gpu_power_limit_watts` is set, the role deploys/enables `nvidia-power-limit.service` on host and applies `nvidia-smi -pm 1` + `nvidia-smi -pl <watts>`.
- To enforce a CUDA 12.8-class host baseline in automation, set `host_nvidia_gpu_min_installed_driver_major: 570`.
