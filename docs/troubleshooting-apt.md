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

## Repair the affected host

Run the following checks on the PVE host named in the failure, not on the Ansible
controller or an inference CT.

1. Confirm the base distribution and locate the Zabbix entries:

   ```bash
   . /etc/os-release
   printf '%s %s (%s)\n' "$ID" "$VERSION_ID" "$VERSION_CODENAME"
   pveversion
   sudo grep -RnsE --include='*.list' --include='*.sources' \
     'repo[.]zabbix[.]com' /etc/apt
   ```

2. Back up and edit the specific file found above. This example assumes the
   conventional `zabbix.list` filename; use the actual filename on your host.

   ```bash
   apt_repair_source=/etc/apt/sources.list.d/zabbix.list
   sudo cp -a -- "$apt_repair_source" \
     "${apt_repair_source}.$(date +%Y%m%d%H%M%S).bak"
   sudoedit "$apt_repair_source"
   ```

   For the reported Zabbix 7.4 / Debian 13 host, check these values against the
   [Zabbix package installation instructions](https://www.zabbix.com/documentation/7.4/en/manual/installation/install_from_packages/debian_ubuntu):

   | Setting | Logged value | Value for the reported Debian 13 host |
   |---|---|---|
   | Repository URI | `http://repo.zabbix.com/zabbix/7.4/stable/debian` | `https://repo.zabbix.com/zabbix/7.4/stable/debian` |
   | Distribution suite | `bookworm` | `trixie` |

   Preserve the existing architecture, components, and `signed-by` keyring.
   For deb822 `.sources` files, the corresponding fields are `URIs` and `Suites`.
   Use the vendor's Debian 13 release configuration if its required keyring or
   package layout differs. Do not replace `bookworm` across all APT sources or
   change the installed Zabbix major version as a workaround.

3. If downloads still fail, inspect the HTTPS response without installing it:

   ```bash
   apt_repair_metadata=$(mktemp)
   curl --fail --location --proto '=https' --proto-redir '=https' \
     --output "$apt_repair_metadata" \
     https://repo.zabbix.com/zabbix/7.4/stable/debian/dists/trixie/InRelease
   head -n 1 "$apt_repair_metadata"
   rm -- "$apt_repair_metadata"
   ```

   A valid InRelease starts with `-----BEGIN PGP SIGNED MESSAGE-----`. This is a
   format check, not signature verification. A redirect to a login page, HTML, or
   an HTTP error needs to be fixed at the repository/proxy/network layer. Keep TLS
   verification enabled. APT and curl may have different proxy configuration, so
   a successful curl request alone is insufficient.

4. Require a successful, authenticated refresh of all enabled sources:

   ```bash
   sudo apt-get --error-on=any update
   ```

   If Zabbix is no longer used, an alternative is to disable only its affected
   entry: comment out that `deb` line in a `.list` file, or set `Enabled: no` on
   that Zabbix stanza in a `.sources` file. This stops package updates from that
   repository; do it only when that is intended. Preserve other sources, including
   Debian and Proxmox, and require the same successful APT refresh afterward.

5. Rerun the original playbook from the controller:

   ```bash
   ansible-playbook -i inventory/ host_nvidia_gpu.yml -D -l pve-01-nas
   ```

Do not skip the cache update to continue with stale metadata. The GPU role does
not manage Zabbix or silently disable third-party sources.

## Warnings that did not stop this run

The Python interpreter discovery message, automatic top-level fact injection
deprecation, and `apt_repository` deprecation are independent of this APT failure.
Changing the Python interpreter or suppressing these warnings will not repair the
repository response. The run stopped before driver installation, so it does not
establish NVIDIA driver, CUDA, or vLLM compatibility on the target.

## Validation scope

The malformed-InRelease failure can be reproduced with isolated local APT state.
Regression tests exercise the role's failure reporting and ensure it stops before
CUDA keyring/repository changes. These checks do not establish the condition of
the remote Zabbix endpoint or the user's PVE host. Apply the source repair and
verify `apt-get --error-on=any update` on that host before rerunning deployment.
