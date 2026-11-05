# NVIDIA/CUDA dependency failures after storage recovery

## What the reported failure establishes

After reclaiming the full root filesystem, the next run passed APT refresh and
kernel-header installation but failed the read-only NVIDIA install simulation:

```text
cuda-drivers -> nvidia-open >= 620.70.06, but 615.71.10-1 selected
nvidia-driver-cuda -> nvidia-persistenced = 615.71.10-1
nvidia-kernel-support -> nvidia-modprobe = 615.71.10-1
nvidia-persistenced 620.70.06-1 -> libnvidia-cfg1 = 620.70.06-1
cuda-nsight-compute-13-5 -> nsight-compute-2026.4.0, not selected
```

APT could not resolve the requested package set. This is a package-state/version
selection failure, not another Ansible temporary-directory failure. Freeing disk
space does not complete a previously interrupted package operation. An incomplete
installation is possible after the prior disk-full incident, but installed state,
holds, pinning, and repository availability must be inspected before attributing
all version conflicts to that incident.

The toolkit task previously used `failed_when: false`, which could make an APT
failure appear as `ok` and continue with a broken package state. It now propagates
APT failures immediately. Optional compiler checking does not permit unsuccessful
package-manager transactions. This change reports the original error sooner; it
does not automatically repair dpkg state or choose a driver branch.

## Confirmed package state and reviewed repair plan

The follow-up audit showed 64 unpacked/unconfigured CUDA 13.5 packages and a
pending `mailcap` trigger. No holds were reported. The inspected NVIDIA driver
packages were consistently installed at `615.71.10-1`; `620.70.06-1` was available
as a candidate from the same official NVIDIA repository. The initial solver
output did not establish that mixed driver versions were actually installed.

`nsight-compute-2026.4.0` was missing, while its required version
`2026.4.0.10-1` was available. The no-removal repair simulation proposed exactly:

- Add `nsight-compute-2026.4.0`.
- Configure the 64 pending packages and triggers.
- Upgrade zero packages and remove zero packages.

A subsequent `--assume-no` check reported 404 MB of archives and 1,572 MB of
additional installed space, fitting within the reported 5.8 GB available with
room for both archives and unpacking. The reviewed repair command is:

```bash
apt-get --no-remove --fix-broken install
dpkg --audit
apt-get check
df -hT /
```

This repair preserves the installed driver branch. If the interactive plan has
changed from the reviewed one-package addition and zero upgrades/removals,
review it again before proceeding. Successful execution still requires verifying
that the audit is empty and `apt-get check` completes without errors; the plan
alone is not evidence that repair ran.

The user subsequently applied the reviewed transaction successfully: Nsight
Compute was added, the 64 pending packages and `mailcap` trigger completed,
`dpkg --audit` produced no output, and `apt-get check` succeeded. Available root
space was 3.9 GB afterward. This confirms recovery of package consistency without
upgrading the installed NVIDIA driver branch. A subsequent host-role run completed
its DKMS, device, and service checks; see the [reported deployment result](troubleshooting-nvidia-nodes.md#reported-deployment-result)
for the validation scope and remaining multi-GPU check.

## Inspect before applying a repair

Run on the affected PVE host:

```bash
dpkg --audit
apt-mark showhold
apt-cache policy cuda-drivers nvidia-open nvidia-driver-cuda nvidia-persistenced nvidia-modprobe libnvidia-cfg1 nvidia-kernel-support cuda-nsight-compute-13-5 nsight-compute-2026.4.0
LC_ALL=C apt-get -s --no-remove --fix-broken install
```

The last command is a simulation. Preserve its exit status and review the entire
proposed package list. Check whether all required versions are available from the
intended repository, whether a hold/pin explains a selection, and whether the
proposal keeps a consistent NVIDIA branch. A simulation that fails does not
authorize forcing a repair or removing packages.

Before an actual transaction, verify download and installed-size requirements
against free space on `/`, APT's archives directory, DKMS storage, and `/boot`.
The reported host had only 5.8 GB available after cache recovery. Package archives
and unpacked files can coexist during installation; the download size alone is
not the peak storage requirement.

The role now performs `dpkg --audit` before NVIDIA repository/package operations
and refuses to proceed with unfinished state. That precondition prevents an
interrupted installation from being obscured by a later candidate-version error.

If a reviewed no-removal repair is possible, apply that specific plan and confirm
`dpkg --audit` is clear and the NVIDIA install simulation succeeds before rerunning
the host role. If the plan requires removals, downgrades, changing holds, or a
different driver branch, identify those changes explicitly first. Do not bypass
signature/dependency checks, purge the Proxmox meta package, or remove bootable
kernels to make a solver error disappear.

Full GPU readiness still requires successful DKMS/module checks and a working
`nvidia-smi` after package state has been repaired.
