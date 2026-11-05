# APT repository failures before NVIDIA setup

## Identify the failing component

`nvidia_cuda_repo_common` refreshes all enabled APT repositories while installing
its bootstrap packages. A failure at this point occurs before this role installs
the CUDA keyring or configures the NVIDIA repository. A broken third-party source
can therefore stop GPU preparation even when its packages are unrelated to NVIDIA.
The role preserves the original APT error and adds recovery guidance.

The reported PVE 9.2 run at commit `fddb56d` failed while downloading:

```text
http://repo.zabbix.com/zabbix/7.4/stable/debian/dists/bookworm/InRelease
Clearsigned file isn't valid, got 'NOSPLIT'
```

`NOSPLIT` means that APT could not parse the response as clearsigned metadata.
An HTTP authentication/error page, a proxy or filtering gateway, or an incorrect
repository URL can cause it. This message alone does not prove that Zabbix stopped
signing its repository or that a signing key expired. Do not use `trusted=yes`,
`allow_unauthenticated`, or options that allow insecure repositories to bypass it.

PVE 9 uses Debian 13 (`trixie`), whereas `bookworm` is Debian 12 (PVE 8's base).
The logged source therefore also needs a distribution check. A stale suite and an
invalid HTTP response are separate issues; the log does not prove which upstream
network component returned the invalid response.

## Confirmed observations and mitigation

The follow-up checks established:

| Check | Result |
|---|---|
| Host distribution | Debian 13 (`trixie`) |
| Configured Zabbix source | `/etc/apt/sources.list.d/zabbix.sources`, HTTP, `bookworm` |
| Initial HTTP HEAD request | HTTP 404 with `Content-Type: text/html` |
| Initial HTTPS request | Connection failed before TLS/HTTP |
| IPv4 HTTPS requests to Zabbix and Debian | HTTP 200, including Zabbix's `trixie/InRelease` |
| `apt-get -o Acquire::ForceIPv4=true --error-on=any update` | Successful refresh of all enabled sources, including signed Zabbix `bookworm` metadata |
| Subsequent normal `apt-get --error-on=any update` | The same Zabbix `NOSPLIT` failure recurred |

The normal-versus-IPv4 APT comparison reproduces the transport-dependent failure;
IPv4-only APT is a verified mitigation for this host, not merely an untested
suggestion after a single failed request.
The earlier invalid response is consistent with `NOSPLIT`; it does not establish
that the upstream repository is unsigned. The old `bookworm` source is a separate
configuration issue: it refreshed successfully with IPv4 but is still the wrong
base distribution for this host.

One NSS lookup expanded the hostname with the site's search suffix and returned
a different IP from curl. Later IPv4 lookups of the bare name, the absolute name,
and a `ndots:1` override all agreed. The default resolver/dual-stack retrieval path
remains implicated, but the exact DNS or network fault is not established. There
is no evidence supporting a permanent `ndots` change or a permanent block of all
HTTPS traffic. Do not
hardcode the working IP or disable host IPv6 based on these results.

### Apply the opt-in workaround with the host role

First retry a normal `apt-get --error-on=any update`. If it now succeeds, leave
the option disabled: a transient failure does not require a permanent transport
override. If the normal refresh still fails while IPv4-only succeeds, set this
only for the affected host in inventory. This comparison was completed on the
reported host and the normal refresh failed again, so the override applies there:

```yaml
host_nvidia_gpu_apt_force_ipv4: true
```

The updated `host_nvidia_gpu` role writes
`/etc/apt/apt.conf.d/99-pve-inference-ipv4` before invoking the shared CUDA repository
role. Its directive is:

```text
Acquire::ForceIPv4 "true";
```

This selects IPv4 for all APT operations on that host, including Ansible's APT
module, while preserving TLS and package-signature verification. It does not
disable host/guest IPv6. The default is `false`; rerunning the role with `false`
removes only its owned override file. Other APT configuration is preserved.
The file path is configurable with `host_nvidia_gpu_apt_force_ipv4_config_path`.

## Repair the affected Zabbix source and rerun

Run host-side commands on the original failing PVE host. The inventory alias was
`pve-01-nas`; confirm it refers to the same machine as the diagnostic shell.

1. Back up the confirmed source file and edit only the Zabbix stanza:

   ```bash
   apt_repair_source=/etc/apt/sources.list.d/zabbix.sources
   sudo cp -a -- "$apt_repair_source" \
     "${apt_repair_source}.$(date +%Y%m%d%H%M%S).bak"
   sudoedit "$apt_repair_source"
   ```

   For Zabbix 7.4 on the confirmed Debian 13 host, set these two fields:

   ```text
   URIs: https://repo.zabbix.com/zabbix/7.4/stable/debian
   Suites: trixie
   ```

   Preserve `Types`, `Components`, the existing `Signed-By` keyring, and any
   architecture settings. This is a stanza edit, not a replacement of the whole
   file. Consult the [Zabbix installation instructions](https://www.zabbix.com/documentation/7.4/en/manual/installation/install_from_packages/debian_ubuntu)
   if the release configuration or keyring needs updating. Do not replace
   `bookworm` across all system sources or change the Zabbix major version.

2. If needed, inspect the metadata response over the working IPv4 HTTPS path:

   ```bash
   apt_repair_metadata=$(mktemp)
   curl -4 --fail --location --proto '=https' --proto-redir '=https' \
     --output "$apt_repair_metadata" \
     https://repo.zabbix.com/zabbix/7.4/stable/debian/dists/trixie/InRelease
   head -n 1 "$apt_repair_metadata"
   rm -- "$apt_repair_metadata"
   ```

   A valid InRelease starts with `-----BEGIN PGP SIGNED MESSAGE-----`. This is a
   format check, not signature verification. APT and curl can have different
   resolver or proxy behavior, so a successful curl request alone is insufficient.

3. Require a successful authenticated refresh after the source edit:

   ```bash
   sudo apt-get -o Acquire::ForceIPv4=true --error-on=any update
   ```

   The successful reported run used the old `bookworm` source. The new `trixie`
   source must pass this check independently. If an error names another source,
   repair that source too rather than ignoring it or using stale metadata.

4. Install/apply the updated Collection, set the per-host variable above, and
   rerun from the controller:

   ```bash
   ansible-playbook -i inventory/ host_nvidia_gpu.yml -D -l pve-01-nas
   ```

If Zabbix is no longer used, another option is to set `Enabled: no` on only its
stanza. That stops package updates from that repository and should be intentional.
The GPU role does not silently edit or disable Zabbix sources.

After resolving the underlying network issue, set the IPv4 option back to `false`,
rerun the role, and verify a normal `apt-get --error-on=any update`. Do not change
networking or restart network services on the PVE host merely to remove this APT
workaround.

## Warnings that did not stop this run

The Python interpreter discovery message, automatic top-level fact injection
deprecation, and `apt_repository` deprecation are independent of this APT failure.
Changing the Python interpreter or suppressing these warnings will not repair the
repository response. The run stopped before driver installation, so it does not
establish NVIDIA driver, CUDA, or vLLM compatibility on the target.

## Validation scope

The malformed-InRelease failure can be reproduced with isolated local APT state.
Regression tests exercise failure reporting, stop-before-CUDA behavior, and the
IPv4 override's creation, idempotency, removal, and native APT syntax. The user
verified that an IPv4 APT refresh succeeded on the host and that a subsequent
normal refresh reproduced the failure. A later deployment confirmed that the
role-created IPv4 override, APT bootstrap, CUDA repository setup, and matching PVE
header installation completed. The run then stopped on a remote temporary-directory
space error; see [host storage recovery](troubleshooting-host-storage.md).
The host role subsequently completed its configured GPU checks; see the
[reported deployment result](troubleshooting-nvidia-nodes.md#reported-deployment-result).
Recognition of all four expected GPUs, cold-boot behavior, CT inference, and the
corrected `trixie` Zabbix source remain outside those verified results.
