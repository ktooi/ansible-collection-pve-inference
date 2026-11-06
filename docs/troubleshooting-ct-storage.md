# CT storage becomes read-only despite free space

## Recognize thin-pool exhaustion

Ansible may fail to create its remote temporary directory even when the CT has
free bytes, free inodes, and correct directory ownership. Use `raw` from the
controller to inspect the CT without uploading a module:

```bash
ansible -i inventory/ ct-image -e ansible_user=root -m ansible.builtin.raw -a '
df -hT /
df -i /
findmnt -rn -o SOURCE,OPTIONS /
'
```

Adapt the inventory targets and use the CT's existing SSH key. `pct` commands run
on the PVE host; they are not installed on the Ansible controller.

If mount options contain `emergency_ro`, ext4 has entered an emergency read-only
state. The options may still start with `rw`; that does not establish that writes
work. A failure with `Read-only file system` is not repaired by changing directory
permissions or Ansible's temporary path. Identify the underlying storage failure.

Inspect the PVE host through its own inventory connection:

```bash
ansible -i inventory/ pve-01-nas -b -m ansible.builtin.raw -a '
pvesm status
lvs --reportformat json -o vg_name,lv_name,lv_size,pool_lv,data_percent,metadata_percent,lv_health_status,lv_kernel_major,lv_kernel_minor
vgs -o vg_name,vg_size,vg_free
pvs -o pv_name,vg_name,pv_size,pv_free
journalctl -k -b --no-pager | tail -n 100
'
```

Match the CT rootfs to its LV and thin pool. Map kernel `dm-N` errors using the
current `lv_kernel_minor` values; device numbers can change after reboot. Check
other guests using the same pool when errors refer to a different LV.

In the reported deployment, these observations established the storage blocker:

| Observation | Result |
|---|---|
| CT 102 root filesystem | 503 GiB total, 392 GiB available; inodes 1% used |
| CT 102 mount/write state | `emergency_ro`; temporary directory creation failed with `Read-only file system` |
| Shared `local-lvm-vm` thin pool | 3.69 TiB, data 100%, health `out_of_data` |
| Thin-pool metadata | 7.54% used |
| Free extents in `local-lvm-vm` VG | 376 MiB |
| Kernel I/O errors on `dm-50` | Mapped to `vm-123-disk-0`; CT 102 was `dm-15` |

The CT's free space describes its virtual filesystem. New writes also need
physical blocks in the shared thin pool. Increasing the CT's virtual disk size
does not supply those blocks. The separate PVE root filesystem and the
`local-lvm` pool do not automatically provide capacity to `local-lvm-vm`.
These observations identify data exhaustion, not thin-pool metadata exhaustion;
they do not establish a need for thin-metadata repair.

## Recover capacity before repairing filesystems

1. Stop model downloads and other writes to the exhausted pool. For this CT, a
   controller-side request is:

   ```bash
   ansible -i inventory/ ct-image -e ansible_user=root -m ansible.builtin.raw \
     -a 'systemctl stop --no-block vllm.service; systemctl show vllm.service -p ActiveState -p SubState'
   ```

   `--no-block` requests the stop; confirm the service reaches `inactive` before
   treating it as stopped. Coordinate other affected guests with their owners.
2. Restore physical pool capacity using a reviewed storage plan: extend the pool
   using verified available space, move selected volumes to storage with enough
   capacity, or remove specifically identified unused volumes/snapshots through
   PVE. Check ownership, existing data, backups, and destination capacity first.
   A disk or partition that appears unmounted is not necessarily unused.
3. Verify that the pool has free data blocks and no longer reports `out_of_data`.
   Leave headroom for continued writes; consuming the last few hundred MiB of VG
   free space does not provide a durable recovery for a multi-TiB pool.
4. Identify filesystems affected by I/O errors. For CT ext4 rootfs recovery,
   arrange downtime and a usable backup outside the exhausted pool, stop the CT,
   and verify its rootfs is unmounted before an offline filesystem check. Review
   the findings before applying repairs. Do not force a read-write remount or run
   filesystem repair against a mounted filesystem.
5. Restart the CT after the storage and filesystem checks pass. Verify mount
   options, a temporary-directory write, normal Ansible module execution, and
   fresh kernel logs before resuming model downloads.

Do not shrink an existing root disk, delete another guest, or create a snapshot
on the full pool as a recovery shortcut. Removing files inside a guest does not
necessarily return blocks to the thin pool: discard support and snapshot
references affect reclamation. Do not run blind trim operations on an affected
read-only filesystem.

## An undo-file error during offline repair

On Debian's e2fsck 1.47.2, an MMP-enabled filesystem combined with `-z` can
fail with `Undo file corrupt` and exit code 8. The following generic message
about an unreadable superblock does not by itself establish superblock damage.
This failure was reproduced on a clean, disposable ext4 file with a fresh undo
file; the failed attempt left the test filesystem bytes unchanged. Omitting
`-z` allowed the check to complete. A separate test with an incorrect free-block
counter also repaired successfully without `-z` and passed a read-only recheck.

The [MMP check in e2fsck 1.47.2](https://github.com/tytso/e2fsprogs/blob/v1.47.2/e2fsck/unix.c#L1753)
reopens the filesystem. In the reproduced case, the
[undo I/O implementation](https://github.com/tytso/e2fsprogs/blob/v1.47.2/lib/ext2fs/undo_io.c#L550)
wrote a zero undo block-size field before that reopen, which it then rejected.
Keep the failed undo file and logs. Do not apply an unvalidated undo file or
select the generic alternate-superblock offsets solely from that message.

Confirm the expected device is offline and its superblock can be read through a
normal reader such as `dumpe2fs -h`. With an appropriate backup or confirmation
that the target data is reproducible, omit `-z` from the reviewed repair command
and inspect its result and read-only verification. This works around the undo
I/O failure; it does not resolve any remaining filesystem errors automatically.

## Resume inference and prevent recurrence

Restarting a systemd service is not proof that a model has downloaded or its API
is listening. Once storage writes work, check current service logs and run the
configured API check with `playbooks/validate.yml`. Investigate any remaining
Hugging Face connection errors separately; a successful IPv4 request to the Hub
home page does not verify every model-download endpoint or the service's network
environment.

After I/O errors, a cached model file may have the expected byte count but
incorrect contents. For example, `invalid JSON in header` while opening a
safetensors file requires checking the weight contents, not only cache
completion markers and sizes. Compare each file with its Hub metadata hash
(LFS SHA-256, or Git blob SHA-1 for ordinary files) at the expected model
revision. Validate safetensors headers and replace only confirmed damaged
files using the model client's download path, with enough physical pool space
for the replacement and temporary files.

Before creating additional CTs or downloading models, budget physical capacity
for all guests, Python environments, model caches, temporary downloads, and logs.
Monitor both thin-pool data and metadata usage, with alerts early enough to act.
Automatic pool extension also requires available extents in the correct VG;
enabling it alone cannot grow a VG that has no capacity. The Collection does not
automatically resize physical storage, delete guest data, or repair filesystems.

For a full PVE host root filesystem, see
[host storage exhaustion](troubleshooting-host-storage.md). For LVM-thin storage
behavior, see the [Proxmox VE storage documentation](https://pve.proxmox.com/pve-docs/chapter-pvesm.html#storage_lvmthin).
