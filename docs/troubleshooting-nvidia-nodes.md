# Missing core NVIDIA nodes after successful module loading

## Confirmed failure

The reported run passed package-state checks, DKMS readiness, and loading of
`nvidia`, `nvidia_uvm`, `nvidia_modeset`, and `nvidia_drm`. It then failed because
one or both critical paths, `/dev/nvidiactl` and `/dev/nvidia-uvm`, were missing.
The role previously requested only:

```bash
nvidia-modprobe -u -c=0
```

The user confirmed that only `/dev/nvidia-uvm` and `/dev/nvidia-uvm-tools` existed.
Running `nvidia-modprobe -c=0` created `/dev/nvidia0`, and `nvidia-smi -L` then
recognized the RTX 3090. This establishes functioning GPU/driver access after
core-node creation. It does not establish that `/dev/nvidiactl` was present in
the earlier directory listing.

## Cause and correction

In the [official helper source](https://github.com/NVIDIA/nvidia-modprobe/blob/64fcfcf6df0dd56c81ee860a86fb97ae692a2105/nvidia-modprobe.c),
`-u` selects the UVM branch instead of the core-device branch. `-c=0` therefore
requests UVM devices when combined with `-u`, not `/dev/nvidia0` or `/dev/nvidiactl`.
The [core filename mapping](https://github.com/NVIDIA/nvidia-modprobe/blob/64fcfcf6df0dd56c81ee860a86fb97ae692a2105/modprobe-utils/nvidia-modprobe-utils.h)
uses minor 255 for `/dev/nvidiactl`.

The role now requests the two families separately:

```bash
nvidia-modprobe -c=0 -c=255
nvidia-modprobe -u -c=0
```

The first invocation requests GPU 0 and the control node explicitly. The second
requests UVM and UVM-tools nodes. `nvidia-modprobe -u` without a `-c` argument
loads the UVM module but does not explicitly request creation of its nodes.

The same sequence is used before/after module loading, in the post-reboot recovery
path, and in `nvidia-uvm-devices.service`. The service retains its ordering before
`pve-guests.service` and waits for the critical character devices. Existing valid
nodes are handled by NVIDIA's helper; the role does not manually guess device
major numbers or delete placeholder files.

## Verify and resume

On the affected host, confirm the critical paths after requesting both families:

```bash
nvidia-modprobe -c=0 -c=255
nvidia-modprobe -u -c=0
stat -c '%F %n' /dev/nvidia0 /dev/nvidiactl /dev/nvidia-uvm
nvidia-smi -L
```

All three paths should be character devices. If the helper fails or a path is
still missing, retain its exit code and stderr and inspect GPU PCI binding,
NVIDIA kernel logs, and driver/module state. A loaded kernel module alone does
not prove that it owns the intended GPU. Do not detach a device from `vfio-pci`
or reset a GPU assigned to an active guest as an automatic recovery step.

Missing-node failures now include each critical path's existence/type and both
helper invocations' return codes and output, rather than hiding errors behind
`failed_when: false`.

Apply the updated Collection and rerun the original playbook with the existing
IPv4 option. Verify persistenced, the boot-time node service, and final
`nvidia-smi` checks complete. Local regression tests cover helper argument
semantics, unit command rendering/order, and failure diagnostics using a helper
fixture; they do not load NVIDIA modules or create real device nodes. Cold-boot
validation remains a separate check on the actual PVE host.

## Reported deployment result

The user reran the host playbook with the node fix and reported:

```text
pve-01-nas : ok=81 changed=5 unreachable=0 failed=0 skipped=30 rescued=0 ignored=0
```

The dpkg precondition, DKMS/module checks, core/UVM character-device assertions,
persistenced startup, updated boot-time unit, and final `nvidia-smi` checks all
completed. This verifies the configured host-role checks on the running system;
it does not establish cold-boot behavior or CT/vLLM inference.

The manual GPU inventory shown during troubleshooting contained one RTX 3090.
The user subsequently reported that four cards should be connected. Recognition
of all four remains a separate open validation item: PCI enumeration, NVIDIA
driver registration, device minors, and userspace inventory must be compared
before attributing it to device-node creation or recommending a reboot.
