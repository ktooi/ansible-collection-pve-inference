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

For this host, the user reported that all four cards worked under PVE 8. Firmware
capability has a known working baseline; do not assume Above 4G Decoding is
disabled or change BIOS settings solely because of the new log. The current
command line already contains `pci=realloc` and `pci=assign-busses` plus the site's
IOMMU/graphics arguments. Adding those parameters again is not a new remedy.

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

### Current-kernel security requirement and boot readiness

This host is confirmed to use UEFI with its active entry pointing to
`\EFI\proxmox\shimx64.efi` and a populated GRUB configuration. Its root is
ext4/LVM. The absent `/etc/kernel/proxmox-boot-uuids` file means no ESP sync list
is configured for `proxmox-boot-tool`; it does not establish a broken GRUB
installation. Do not initialize ESP configuration to address this GPU error.

The operator requires retaining the current kernel series for security and has
ruled out booting older builds. Do not use the available 6.17/6.8 entries for a
rollback test. Package policy confirmed `7.0.14-28-pve` as installed and current
candidate, while the running kernel was `7.0.14-26-pve`. The `-28` kernel and
initramfs files exist, but `modinfo -k 7.0.14-28-pve -F version nvidia` failed:
there was no NVIDIA module for that target kernel. The previously reported DKMS
readiness for `-26` does not cover `-28`.

Root free space had also fallen to 1.3 GB. Prepare sufficient capacity, the exact
target kernel's headers, and the matching NVIDIA 620 module before rebooting to
`-28`. Do not assume an installed kernel menu entry is GPU-ready. Keep existing
PCI/IOMMU arguments for the first test on the prepared, updated kernel; booting a
newer build is a recovery candidate, not proof that BAR allocation is fixed.

Resource and header availability checks are read-only:

```bash
du -xsh /var/cache/apt/archives /var/lib/dkms /usr/lib/modules /var/log
vgs pve --units g -o vg_name,vg_size,vg_free
lvs pve/root --units g -o vg_name,lv_name,lv_size,lv_attr
apt-cache policy proxmox-headers-7.0.14-28-pve
```

Use the observed capacity to choose cache cleanup or a reviewed storage
allocation. Do not shrink the guest thin pool or remove guest disks to make room.

The follow-up check found only 1.2 GB of APT archives, 16 GiB unallocated in VG
`pve`, and an active 76.19 GiB root LV. The exact `-28` headers were available but
not installed. For this host, the proposed preparation allocates 8 GiB of that
unallocated space to root and builds only the target NVIDIA module:

```bash
# Run this extension once; do not repeat it when retrying a later failed step.
lvextend --resizefs --size +8G /dev/pve/root &&
apt-get --no-remove install proxmox-headers-7.0.14-28-pve &&
dkms install -m nvidia -v 620.70.06 -k 7.0.14-28-pve &&
depmod -a 7.0.14-28-pve &&
update-initramfs -u -k 7.0.14-28-pve

modinfo -k 7.0.14-28-pve -F version nvidia
dkms status -m nvidia -v 620.70.06 -k 7.0.14-28-pve
dpkg --audit
df -hT / /boot
```

This is a host-specific storage change, not an automatic Collection action. The
extension leaves 8 GiB unallocated in `pve`. Stop if any preparation step fails;
header package hooks can invoke other registered DKMS modules too. Before a
planned reboot, require NVIDIA `620.70.06` installed for `-28`, a clean dpkg audit,
and adequate remaining disk space. The old loaded module remains in memory until
replaced; an on-disk `modinfo` check does not establish runtime consistency.
The operator executed this preparation successfully. The root LV grew to 84.19
GiB, with 8.6 GB available in the filesystem. The exact `-28` headers installed,
`modinfo` returned `620.70.06`, and DKMS reported that version installed for
`7.0.14-28-pve`. The dpkg audit produced no output and the target initramfs was
regenerated. `No /etc/kernel/proxmox-boot-uuids found, skipping ESP sync` is
consistent with this host's GRUB setup; it was not an initramfs-generation
failure. Do not repeat the root extension when proceeding to the boot test.

With guests stopped or migrated and console access available, select the
prepared updated kernel for the next boot only:

```bash
proxmox-boot-tool kernel pin 7.0.14-28-pve --next-boot && systemctl reboot
```

Proxmox documents this selection for GRUB systems without managed ESP sync too.
Use the one-boot selection rather than a permanent pin that could prevent future
security updates from becoming the boot default. Existing PCI/IOMMU arguments
remain the baseline for this test. After reconnecting, inspect:

```bash
uname -r
cat /proc/driver/nvidia/version
nvidia-smi --query-gpu=index,pci.bus_id,name,driver_version --format=csv,noheader
lspci -Dnnk -d 10de:
journalctl -k -b --no-pager | grep -Ei 'NVRM|nvidia.*(error|fail)|BAR.*(no space|failed|can.t assign)'
```

Require the `-28` kernel, loaded NVIDIA `620.70.06`, four physical GPUs, and no
corresponding BAR/probe failures in the current boot. A successful module build
does not establish those runtime results; reboot validation is still pending.

Past kernel behavior can sometimes be compared without booting old software by
reading archived logs, if retained:

```bash
journalctl --list-boots
# Replace this value with the known prior boot's ID from the list.
gpu_diag_boot_id=REPLACE_WITH_BOOT_ID
journalctl -k -b "$gpu_diag_boot_id" --no-pager | grep -E 'Linux version|Command line|root bus resource|BAR|NVRM'
```

Missing historical logs do not prove a kernel regression. If BAR failures persist
on the prepared current kernel, inspect PCI bridge/root windows and available
historical evidence before changing further resource-allocation settings.

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
