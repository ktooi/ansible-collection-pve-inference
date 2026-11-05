# nvidia_cuda_repo_common

Configure NVIDIA's official CUDA APT repository on Debian-based hosts and CTs.

## Variables

- `nvidia_cuda_repo_common_repo_url`: CUDA apt repo URL
- `nvidia_cuda_repo_common_keyring_deb_url`: CUDA keyring deb URL
- `nvidia_cuda_repo_common_keyring_path`: apt signed-by keyring path
- `nvidia_cuda_repo_common_list_filename`: apt source list filename

## Usage

```yaml
- ansible.builtin.include_role:
    name: ktooi.pve_inference.nvidia_cuda_repo_common
  vars:
    nvidia_cuda_repo_common_repo_url: "https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/"
    nvidia_cuda_repo_common_keyring_deb_url: "https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/cuda-keyring_1.1-1_all.deb"
```

## APT failures before CUDA configuration

The bootstrap step refreshes all enabled APT repositories. If an existing source
fails, the role stops before installing the CUDA keyring or configuring NVIDIA's
repository, preserves the original APT error, and explains how to recover.

For `NOSPLIT`, Zabbix sources left on `bookworm` after upgrading to PVE 9, and
safe recovery steps, see [APT troubleshooting](../../docs/troubleshooting-apt.md).
The role does not rewrite unrelated sources or disable signature verification.
