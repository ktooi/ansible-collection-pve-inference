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
