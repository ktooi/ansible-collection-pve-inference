# Host storage exhausted during NVIDIA preparation

If `df` inside a CT reports free space but writes fail with `Read-only file
system` or ext4 shows `emergency_ro`, inspect the backing thin pool instead:
see [CT storage recovery](troubleshooting-ct-storage.md).

## Recognize the failure

The reported run successfully applied the IPv4 APT override, refreshed package
metadata, configured the CUDA repository, and installed matching PVE headers.
It then stopped before the next `nvcc` probe with:

```text
mkdir: cannot create directory '/home/romuska_palo/.ansible/tmp/ansible-tmp-...': No space left on device
UNREACHABLE!
```

Ansible could not create its remote working directory. The probe itself did not
execute. `failed_when: false` applies to module results, not this transport/setup
failure. Disk blocks or inodes may be exhausted on the filesystem containing the
SSH user's home. The error alone does not identify which resource was exhausted
or which process filled it.

The follow-up `df` results confirmed that `/dev/mapper/pve-root` is a 75 GB ext4
filesystem at 100% usage, with zero available bytes. `/`, `/home`, `/var`, and
`/usr/local` share it. Inodes were only 11% used. `/tmp` was a separate, mostly
empty 95 GB tmpfs. This establishes root-filesystem byte exhaustion; changing
Ansible's temporary path to `/tmp` alone would not provide the disk capacity
needed for headers, package installation, and DKMS. The exact directory consuming
the space requires a usage check.

The usage check found 9.3 GB in `/var/cache/apt/archives`, 4.0 GB in `/var/log`
(including 3.9 GB of journals), 10 GB in `/usr/local`, 12 GB in installed kernel
modules, 1.5 GB in `/usr/src`, and 16 GB in `/var/lib/vz`. The first recovery action
is to reclaim the re-downloadable APT archives rather than remove packages or
guest data. With no other package-management operation active, run:

```bash
apt-get clean
df -hT /
apt-get --error-on=any update
```

Measure the resulting available space rather than assuming all cache usage will
become user-available space; filesystem reservations also affect availability.
These commands do not uninstall drivers, kernels, or CUDA packages. The final
APT refresh uses the already-applied IPv4 override.

On the reported host, this recovery reduced used space from 75 GB to 65 GB and
restored 5.8 GB of user-available space (92% usage). A subsequent normal
`apt-get --error-on=any update` succeeded. This confirms recovery from the
observed storage and APT blockers. The host role subsequently finished its
configured checks; see the [reported deployment result](troubleshooting-nvidia-nodes.md#reported-deployment-result).

The run reported only two changed tasks: the APT override and kernel headers.
The toolkit package task returned `ok`, so the log does not establish that a new
CUDA toolkit download or installation caused the exhaustion.

## Inspect without requiring Ansible temporary files

Run on the affected PVE host through an existing SSH session:

```bash
df -hT / /home/romuska_palo /tmp /var /usr/local
df -i / /home/romuska_palo /tmp /var /usr/local
```

Alternatively, the controller can use `raw`, which does not upload a Python module:

```bash
ansible -i inventory/ pve-01-nas -b -m ansible.builtin.raw \
  -a 'df -hT / /home/romuska_palo /tmp /var /usr/local'
ansible -i inventory/ pve-01-nas -b -m ansible.builtin.raw \
  -a 'df -i / /home/romuska_palo /tmp /var /usr/local'
```

Use the original inventory target, SSH user, and filesystem paths. Identify which
paths share a mount before selecting a cleanup location. If bytes are exhausted,
inspect usage on that mount; for example:

```bash
du -xhd1 /home/romuska_palo/.ansible /var/cache/apt /var/log /usr/local /usr/src /usr/lib/modules
```

If inodes are exhausted, use `du --inodes -x -d1` on the affected directory instead.
If `df` and `du` disagree substantially, inspect deleted-but-open files (for example
with `lsof +L1`, if installed), filesystem quotas, and storage-pool health. Do not
restart PVE services or stop guests solely on the basis of a space estimate.

## Recover the identified resource

- If APT's downloaded archives are large and on the full filesystem, `apt-get clean`
  can reclaim that cache. It does not uninstall packages. First confirm that no
  other package-management operation is active. Cleaning a different filesystem
  will not repair the home filesystem.
- If old Ansible temporary directories are responsible, inspect only this SSH
  user's abandoned directories and remove selected inactive artifacts. Do not
  remove another active playbook's working directory.
- If kernels or CUDA versions dominate usage, plan package-managed removal after
  identifying what is still required. Preserve the running kernel and a known
  bootable fallback until NVIDIA/DKMS readiness is established. The `apt autoremove`
  suggestion in the log is not a reviewed removal plan. Do not delete `/usr/src`,
  `/usr/lib/modules`, CUDA directories, or VM/CT storage by hand.
- If the filesystem genuinely needs more capacity, expand the relevant filesystem
  or storage allocation through the host's storage-management procedure.

If only the home filesystem is full and a separate `/var/tmp` filesystem has
enough space and inodes, a per-host `ansible_remote_tmp` location can restore
module execution temporarily. Use a private directory owned by the actual SSH
user, not a shared world-writable working directory. This does not create space
for package installation, kernel headers, or DKMS on other full filesystems.

The Collection does not automatically purge kernels, prune logs, or change the
SSH user's temporary directory to hide resource exhaustion.

## Resume validation

After reclaiming capacity or correcting the filesystem allocation:

1. Recheck free bytes and inodes and confirm the SSH user can create a temporary
   directory under its configured Ansible working directory. A controller-side
   `ansible -i inventory/ pve-01-nas -m ansible.builtin.ping` checks normal module
   upload/execution once space is available.
2. Verify an authenticated APT refresh with the existing IPv4 workaround.
3. Rerun the original host playbook, retaining the IPv4 option in host inventory.
4. Confirm DKMS, device nodes, and `nvidia-smi` checks complete before treating GPU
   preparation as successful.

The role's PATH-based `nvcc` probes now use the shell module because `command -v`
is a shell builtin. This corrects a separate false-negative detection bug; it
does not repair an exhausted filesystem. Missing `nvcc` is still handled by the
existing toolkit installation and versioned-directory fallback logic.
