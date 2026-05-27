# nvidia_cuda_repo_common

Debian系ノード向けに NVIDIA 公式 CUDA apt repository を設定する共通 role です。

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
