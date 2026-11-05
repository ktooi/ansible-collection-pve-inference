# Four PCI GPUs but an incomplete NVIDIA userspace inventory

## Observed state

The reported host-role run completed its configured checks with one visible RTX
3090. The user expected four cards. Follow-up PCI inventory showed four RTX 3090
display functions at `0000:05:00.0`, `0000:06:00.0`, `0000:09:00.0`, and
`0000:0a:00.0`. Only `05:00.0` reported `Kernel driver in use: nvidia`, and only
that GPU appeared under `/proc/driver/nvidia/gpus`. The other display functions
had no reported driver binding. Their PCI presence does not establish driver
initialization or guest assignment.

The same follow-up shell also reported:

```text
Failed to initialize NVML: Driver/library version mismatch
NVML library version: 620.70
```

Creating numbered device nodes alone cannot register the other cards with the
driver or correct a kernel/userspace version mismatch. Do not create arbitrary
minors or unbind PCI devices to make an inventory appear complete.

### Confirmed module mismatch and PCI resource failure

Further diagnostics established two independent faults:

| Component | Observed result |
|---|---|
| Running kernel | `7.0.14-26-pve` |
| Loaded NVIDIA module | `615.71.10` |
| On-disk NVIDIA module | `620.70.06` |
| DKMS | `nvidia/620.70.06` installed for `7.0.14-26-pve` |
| Clean library-search `nvidia-smi` | Still fails with NVML library `620.70` mismatch |
| GPUs at `06:00.0`, `09:00.0`, `0a:00.0` | BAR allocation failed; NVIDIA reported `BAR0 is 0M @ 0x0` and probe failure |

The old module remains loaded while newer modules/libraries are installed. A
planned reboot can load the built 620 module and resolve that version mismatch.
The kernel explicitly reports PCI resource assignment failures for the other
three cards, so a reboot alone is not a demonstrated four-GPU fix.

`BAR ... can't assign; no space` refers to PCI MMIO address allocation, not disk
blocks or free RAM. Repeating APT cache cleanup does not repair it. Firmware's
PCI resource windows and bridge allocation must also accommodate the four GPUs.

## Decide whether a reboot is appropriate

Inspect the loaded module, installed module, current-kernel DKMS state, and the
library search context before rebooting:

```bash
uname -r
cat /proc/driver/nvidia/version
modinfo -F version nvidia
dkms status
command -v nvidia-smi
env -u LD_LIBRARY_PATH /usr/bin/nvidia-smi -L
dmesg -T | grep -Ei 'NVRM|RmInitAdapter|nvidia.*(error|fail)|BAR.*(no space|failed)' | tail -n 80
```

The environment override affects only this local diagnostic process. It does not
change persistent shell or service configuration. The preceding Ansible run had
successful `nvidia-smi` checks, so a difference between interactive and Ansible
library/executable selection must be considered alongside a recent driver update.

If a newer module matching the userspace libraries is installed and built for the
kernel that will boot, a planned host reboot can load it. Schedule guest shutdown
or migration first. If the installed module is still old or missing for the boot
kernel, repair/build that module first; rebooting alone does not create it. If
the clean library-search diagnostic succeeds but the normal command fails, repair
the library path/selection instead of assuming a reboot fixes the shell context.

After version consistency is restored, compare PCI binding, driver registration,
and userspace counts again. If only one card is still driver-bound, inspect the
specific probe failures, PCI resource allocation, and any device overrides or VM
assignment. Do not automatically detach a running guest's GPU.

### PCI BAR allocation recovery

Confirm the host's boot mode and firmware settings before changing persistent
kernel parameters:

```bash
cat /proc/cmdline
if [ -d /sys/firmware/efi ]; then printf 'UEFI boot\n'; else printf 'Legacy BIOS boot\n'; fi
proxmox-boot-tool status
```

For multi-GPU firmware configuration, inspect **Above 4G Decoding** first and
enable it if required for the board's PCI address allocation. Review Resizable
BAR settings and available MMIO windows according to the motherboard/firmware
documentation; the reported 256 MB BAR requests do not establish that large
Resizable BAR was enabled. Do not disable CSM on an existing Legacy installation
without preparing a compatible UEFI boot path.

If bridge windows remain insufficient, the documented Linux `pci=realloc` option
enables reallocation of PCI bridge resources whose BIOS allocations are too
small. Prefer a controlled one-boot test before making it persistent. Preserve
existing kernel, root, IOMMU, and other boot arguments and keep console/recovery
access during the test. The Collection does not edit firmware, reassign PCI
resources at runtime, or automatically reboot for this BAR problem.

For a verified persistent change, use the configuration mechanism of the actual
bootloader: GRUB uses `GRUB_CMDLINE_LINUX_DEFAULT` and `update-grub`; systemd-boot
uses `/etc/kernel/cmdline` and `proxmox-boot-tool refresh`. UEFI boot alone does
not identify which bootloader is active. Do not apply both mechanisms blindly.

References:

- [Linux PCI kernel parameters](https://github.com/torvalds/linux/blob/master/Documentation/admin-guide/kernel-parameters.txt) (`realloc` / `realloc=on`)
- [Proxmox system booting and kernel command line](https://github.com/proxmox/pve-docs/blob/master/system-booting.adoc)

After the planned reboot, check the loaded module version, `nvidia-smi -L`, all
four NVIDIA PCI driver bindings, and fresh BAR/NVRM errors. Require four GPUs in
the role before considering the multi-GPU recovery complete.

## Require the intended inventory

For a host intended to expose all four cards through the NVIDIA driver, set:

```yaml
host_nvidia_gpu_expected_gpu_count: 4
```

The role counts physical `GPU N:` lines in the final `nvidia-smi -L` output and
fails if the count differs. `0` is the compatible default and disables this count
policy. MIG child lines are excluded. This validates recognition; it does not
change PCI bindings or load a GPU the kernel has not registered.

NVML mismatch detection now checks both stdout and stderr. The existing
`host_nvidia_gpu_auto_reboot_on_nvml_mismatch` option remains explicit and defaults
to `false`. Check module readiness and guest impact before enabling it. Local
tests exercise stream detection and count policy without calling reboot.

Four-GPU readiness and a reboot recovery have not yet been demonstrated by the
reported data. The earlier successful playbook establishes only its configured
checks on the running system with one visible GPU.
