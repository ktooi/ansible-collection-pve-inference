# ktooi.pve_inference

**Proxmox VE 上の CT ベース推論環境**を構築・運用するための Ansible Collection です。

設計原則:
- **ホスト側**と**CT 側**の責務分離
- ランタイム差分を `ct_runtime_*` Role に分離
- 宣言的なライフサイクル管理

---

## スコープ

### 含むもの
- PVE ホストの GPU 前提設定
- CT の作成/更新/削除
- CT 内共通ランタイム基盤（ユーザー、ディレクトリ、任意の runtime 用 Python 環境）
- 推論ランタイム導入（初期は vLLM）
- 構築後検証

### 初期スコープ外
- Kubernetes クラスタ構築
- VM 主体の運用
- 複数ノード分散推論の本格対応
- Docker/Podman ネスト運用の主対応

---

## サポート方針（要約）
- **PVE 9.1.x**: 正規サポート（メイン）
- **PVE 8.x**: 互換サポート
- **PVE 9.0.x / その他 9.x マイナー**: ベストエフォート
- 初期メイン経路: **NVIDIA + vLLM**
- 将来の GPU ベンダ/ランタイム拡張を前提

詳細:
- [`docs/support-policy.md`](docs/support-policy.md)
- [`docs/gpu-matrix.md`](docs/gpu-matrix.md)
- [`docs/runtime-matrix.md`](docs/runtime-matrix.md)

---

## Collection と Role の関連図

```mermaid
flowchart TD
    A[playbooks/host_nvidia_gpu.yml] --> B[role: host_gpu_common]
    A --> C[role: host_nvidia_gpu]

    D[playbooks/ct_create.yml] --> E[role: ct_instance]

    F[playbooks/runtime_vllm.yml] --> G[role: ct_runtime_common]
    F --> G2[role: ct_runtime_launcher_common]
    F --> H[role: ct_runtime_vllm]

    I[playbooks/validate.yml] --> J[role: ct_validate]

    C --> K[(PVE host GPU ready)]
    E --> L[(CT exists)]
    G --> M[(CT common runtime ready)]
    G2 --> M2[(shared launcher vars)]
    H --> N[(vLLM systemd service)]
    J --> O[(Validation result)]
```

---

## インストール

### 要件
- Ansible Core `>=2.17`（`community.proxmox >=1.6.0` の要件）
- `community.proxmox >=1.6.0`
- CT ライフサイクル管理用のコントローラー側 Python パッケージ: `proxmoxer >=2.0`、`requests`

`requirements.yml` 例:

```yaml
collections:
  - name: community.proxmox
    version: ">=1.6.0"
```

インストール:

```bash
ansible-galaxy collection install -r requirements.yml
```

Collection のチェックアウト先で、`ansible-playbook` を実行する venv に Python 依存関係をインストールします。

```bash
python -m pip install -r requirements-controller.txt
python -c 'import sys, proxmoxer, requests; print(sys.executable); print("Proxmox dependencies OK")'
```

`ct_instance` は Proxmox API 操作を `localhost` に委譲します。
これらのパッケージは、Ansible コントローラー上で当該タスクが使用する Python から読み込める必要があります。
PVE ホストや CT にインストールしても、この要件は満たせません。
`ansible-galaxy` は Collection をインストールしますが、Python パッケージの依存関係はインストールしません。
import エラーに別の Python パスが表示される場合は、そのパスを指定して `-m pip` と上記の import 確認を実行してください。

---

## 使用方法

### サポート対象 CT ディストリビューション
- Debian: 12, 13
- Ubuntu（LTS）: 22.04, 24.04
- RHEL および主要な RHEL クローン: 9, 10（Red Hat Enterprise Linux / AlmaLinux / Rocky Linux / Oracle Linux）

CT runtime 系 Role は `tasks/variables.yml` と `vars/*.yml` を使ってディストリビューション別変数を読み分ける方式で実装しています。

各 runtime の制約は別途適用されます。新設した native sd.cpp Role は初期段階では
Debian/Ubuntu を対象とし、**実機デプロイ試験待ち**です。
[デプロイ手順](docs/sdcpp-deployment.md)を参照してください。

### ストレージ容量

CT の rootfs サイズは仮想的な割当です。CT 作成やモデル取得の前に、同じプールを使う全ゲストを含めて、実際のストレージ容量を確認してください。
LVM thin-pool が満杯になると、CT 内の `df` に空きがあっても I/O エラーや読み取り専用への移行が発生します。
確認と復旧の手順は [CT ストレージの復旧](docs/troubleshooting-ct-storage.md)を参照してください。

モデル初期化時の Hugging Face 接続エラーについては、[通信の切分けと DNS 設定](docs/troubleshooting-hf-network.md)を参照してください。
サービス実行ユーザーで `single-request-reopen` の効果を確認できた場合は、対象 CT の host_vars に `ct_runtime_vllm_resolver_options: single-request-reopen` を設定できます。


### 1) PVE で API Token を払い出す

CT 管理には、対象ノード/ストレージに対する十分な権限を持つ API Token が必要です。

例（実運用ポリシーに合わせて調整）:

```bash
# automation 用ユーザー作成
pveum user add ansible@pve --password 'REPLACE_ME'

# 必要権限を持つロール作成（例）
pveum role add AnsiblePVE -privs "Sys.Modify VM.Allocate VM.Config.CPU VM.Config.Memory VM.Config.Disk VM.Config.Network VM.Config.Options VM.PowerMgmt Datastore.AllocateSpace Datastore.Audit SDN.Use"

# ユーザーへロール付与
pveum aclmod / -user ansible@pve -role AnsiblePVE

# トークン作成
pveum user token add ansible@pve ci-token --privsep 0
```

Token ID / Secret は `ansible-vault` 等で安全に管理してください。

`ansible-vault` 利用例:

```bash
# 暗号化された変数ファイルを新規作成
ansible-vault create group_vars/pve_hosts/vault.yml

# 既存の暗号化ファイルを編集
ansible-vault edit group_vars/pve_hosts/vault.yml

# vault パスワード入力で実行
ansible-playbook -i inventory.ini playbooks/ct_create.yml --ask-vault-pass

# （代替）vault パスワードファイル利用
ansible-playbook -i inventory.ini playbooks/ct_create.yml --vault-password-file .vault_pass.txt
```

`group_vars/pve_hosts/vault.yml` 例:

```yaml
vault_pve_api_token_secret: "REPLACE_WITH_REAL_TOKEN_SECRET"
vault_ct_root_password: "REPLACE_WITH_STRONG_PASSWORD"
vault_ct_root_pubkey: "ssh-ed25519 AAAA... your-key-comment"
# HF_TOKEN を指定する場合には、ansible-vault 経由で安全に管理してください
vault_hf_token: "hf_xxx"
```

### トラブルシューティング: 403 Forbidden (`Permission check failed (/, Sys.Modify)`)

Token 認証は通るが以下で失敗する場合:

- `403 Forbidden: Permission check failed (/, Sys.Modify)`

API ユーザー/Token の ACL 権限が不足しています。

最小対応:

- Ansible 用ロールに `Sys.Modify` を含める
- 自動化ユーザーに ACL を再付与する（例: `/`）

```bash
pveum role modify AnsiblePVE -privs "Sys.Modify VM.Allocate VM.Config.CPU VM.Config.Memory VM.Config.Disk VM.Config.Network VM.Config.Options VM.PowerMgmt Datastore.AllocateSpace Datastore.Audit SDN.Use"
pveum aclmod / -user ansible@pve -role AnsiblePVE
```

確認:

```bash
pveum user permissions ansible@pve
```

### 補足: `ct_instance_unprivileged: false` は vLLM 必須か?

必須ではありません。vLLM が必要とするのは CT 内での GPU 可視性
（`/dev/nvidia*`、`libcuda.so.1`、`torch.cuda`）です。

運用方針:

- Token / 非 root 自動化なら `ct_instance_unprivileged: true` を推奨
- `ct_instance_unprivileged: false` は必要性が明確な場合のみ利用

### トラブルシューティング: 403 Forbidden (`Permission check failed (/vms/<vmid>, VM.Config.Options)`)

以下で失敗する場合:

- `403 Forbidden: Permission check failed (/vms/<vmid>, VM.Config.Options)`

API ユーザー/Token に CT オプション変更権限がありません。
この Role は `onboot` / `unprivileged` などを設定するため `VM.Config.Options` が必要です。

```bash
pveum role modify AnsiblePVE -privs "Sys.Modify VM.Allocate VM.Config.CPU VM.Config.Memory VM.Config.Disk VM.Config.Network VM.Config.Options VM.PowerMgmt Datastore.AllocateSpace Datastore.Audit SDN.Use"
pveum aclmod / -user ansible@pve -role AnsiblePVE
```

### トラブルシューティング: 403 Forbidden (`Permission check failed (/sdn/... , SDN.Use)`)

以下のようなエラー:

- `403 Forbidden: Permission check failed (/sdn/zones/<zone>/<bridge>, SDN.Use)`

CT ネットワークブリッジが Proxmox SDN 管理で、`SDN.Use` 権限が不足しています。

- ロールに `SDN.Use` を含める
- ACL を再付与（または SDN サブツリーへポリシーに沿って付与）

```bash
pveum role modify AnsiblePVE -privs "Sys.Modify VM.Allocate VM.Config.CPU VM.Config.Memory VM.Config.Disk VM.Config.Network VM.Config.Options VM.PowerMgmt Datastore.AllocateSpace Datastore.Audit SDN.Use"
pveum aclmod / -user ansible@pve -role AnsiblePVE
```

SDN を使わない場合は、`ct_instance_netif` を非 SDN ブリッジへ変更してください。

### トラブルシューティング: 403 Forbidden (`changing feature flags for privileged container`)

以下で失敗する場合:

- `403 Forbidden: Permission check failed (changing feature flags for privileged container is only allowed for root@pam)`

Proxmox の制約です。**privileged CT**（`ct_instance_unprivileged: false`）で feature 変更は `root@pam` のみ許可されます。

対応:

- 推奨: `ct_instance_unprivileged: true` にする
- または `ct_instance_api_user: root@pam` で実行（許容される場合）
- あるいは privileged CT では feature 変更を行わない

注: 本 Collection は privileged CT かつ `root@pam` 以外の場合、`features` パラメータを自動で省略します。

### トラブルシューティング: VM 作成待機で timeout

API モジュールの待機中は進捗が表示されません。既定の `ct_instance_timeout: 600` を増やす前に、PVE 上で実際の作成タスクを確認してください。

```bash
pvenode task list --vmid 102 --source all --limit 5
pvenode task status 'UPID:REPLACE_WITH_CREATION_TASK_ID'
pvenode task log 'UPID:REPLACE_WITH_CREATION_TASK_ID'
```

VMID と UPID は実際の値に置き換えます。タスクが `status=stopped`、`exitstatus=OK` または `WARN*` なら正常終了です。実行中または失敗したタスクはログで原因を確認します。thin-pool の警告だけでは作成失敗とは判断できません。

本 Role は警告付き終了を扱える `community.proxmox.proxmox`（`community.proxmox >=1.6.0`）を使用します。旧実装では `WARNINGS: 1` を成功と判定せず、タイムアウトまで待つ場合があります。タイムアウトからの継続には、返された UPID の成功結果と、ローカル CT の存在確認の両方が必要です。
詳細は [CT Role の手順](roles/ct_instance/README.md#creation-appears-to-wait-without-progress) を参照してください。

### トラブルシューティング: 401 Unauthorized

`401 Unauthorized: Authentication failed!` の場合:

- `ct_instance_api_user` は Token 所有者（例: `ansible@pve`）に一致させる
- `ct_instance_api_token_id` は Token 名（例: `ci-token`）を推奨
  - 本 Collection は従来形式 `<user>!<token_name>` も自動正規化で受け付けます
- ACL が対象パス（例: `/`）に付与されているか確認

簡易 API テスト:

```bash
curl -sk -H "Authorization: PVEAPIToken=ansible@pve!ci-token=REPLACE_WITH_SECRET" \
  https://<PVE_HOST>:8006/api2/json/version
```

### 2) Inventory / 変数を準備

`inventory.ini`:

```ini
[pve_hosts]
pve01 ansible_host=192.0.2.10

[ct_targets]
ct-infer-01 ansible_host=198.51.100.20
```

`group_vars/pve_hosts.yml` 例:

```yaml
ct_instance_api_host: "192.0.2.10"
ct_instance_api_user: "ansible@pve"
ct_instance_api_token_id: "ci-token"
ct_instance_api_token_secret: "{{ vault_pve_api_token_secret }}"
ct_instance_validate_certs: false
ct_instance_password: "{{ vault_ct_root_password }}"
ct_instance_pubkey: "{{ vault_ct_root_pubkey }}"
ct_instance_node: "pve01"
ct_instance_vmid: 120
ct_instance_hostname: "ct-infer-01"
ct_instance_cores: 16            # CT の CPU コア数
ct_instance_memory: 131072       # CT のメモリサイズ (MiB)
ct_instance_rootfs_size: 512     # CT のディスクサイズ (GiB)
ct_instance_storage: "local-lvm"
ct_instance_ostemplate: "local:vztmpl/debian-12-standard_12.0-1_amd64.tar.zst"
ct_instance_enable_nvidia_passthrough: true
```

`group_vars/ct_targets.yml` 例:

```yaml
# CT 作成後に接続するための設定
ansible_user: "root"
# 認証方式はどちらか一方を使用
# ansible_password: "{{ vault_ct_root_password }}"
ansible_ssh_private_key_file: "~/.ssh/id_ed25519"

# Shared launcher values for runtimes with matching LLM semantics.
ct_runtime_launcher_model: "meta-llama/Llama-3.1-8B-Instruct"
ct_runtime_launcher_context_length: 32768   # LLM のコンテキスト長
ct_runtime_launcher_tensor_parallel_size: 4
ct_runtime_launcher_pipeline_parallel_size: 1
ct_runtime_launcher_gpu_memory_utilization: 0.9
ct_runtime_launcher_max_num_seqs: 64
ct_runtime_launcher_max_num_batched_tokens: 8192
ct_runtime_launcher_port: 8000

# ランタイム固有変数も引き続き指定可能
ct_runtime_vllm_dtype: "auto"
ct_runtime_vllm_kv_cache_dtype: "auto"
# 任意: vLLM の Hugging Face Hub ダウンロードを認証する場合
ct_runtime_vllm_hf_token: "{{ vault_hf_token }}"
```

### 調整頻度が高い変数

ハードウェア構成やモデル特性に応じて、次の変数は調整頻度が高くなります。
- `ct_instance_cores`, `ct_instance_memory`, `ct_instance_rootfs_size`
- `ct_runtime_launcher_context_length`
- `ct_runtime_launcher_tensor_parallel_size`, `ct_runtime_launcher_pipeline_parallel_size`
- `ct_runtime_launcher_gpu_memory_utilization`
- `ct_runtime_launcher_max_num_seqs`, `ct_runtime_launcher_max_num_batched_tokens`
- `ct_runtime_vllm_dtype`, `ct_runtime_vllm_kv_cache_dtype`

### Role による前提条件チェック

各 Role は収集値を `ansible_facts[...]` から参照し、`INJECT_FACTS_AS_VARS` が無効でも動作します。ansible-core 2.21 で非推奨となり、2.24 で廃止予定の自動展開された変数への依存を解消しています。

これまで暗黙だった前提条件について、Role 内で明示チェックするようにしました。例えば:
- PVE ホスト側: `host_nvidia_gpu` で Debian 系 / `*-pve` カーネル / `pve-headers-{{ ansible_kernel }}` / `/dev/nvidia*` を確認
- PVE ホスト側: `proxmox-ve` が削除される apt プランを検知した場合は中断
- PVE ホスト側: DKMS 自動ビルド後、`nvidia-*` / `nvidia-current-*` のどちらのモジュール名か判定してロード
- CT 側: `tasks/variables.yml` でディストリビューションとバージョンのサポート可否を先に検証
- CT の vLLM 側: `libcuda.so.1` / `/dev/nvidia*` / venv 内 `torch.cuda` の事前チェックをデフォルトで実施

### 2.5) 後続 Playbook のための CT ログイン設定

`ct_create.yml` 後、runtime/validate Playbook は `ct_targets` へ SSH 接続します。
`group_vars/ct_targets.yml` に少なくとも次のいずれかを設定してください。

- 鍵認証: `ansible_user` + `ansible_ssh_private_key_file`
- パスワード認証: `ansible_user` + `ansible_password`

`ct_instance_password` と `ct_instance_pubkey` を両方設定した場合、どちらの認証方式も利用できます。

### トラブルシューティング: `CT <vmid> already exists on node`

`state: present` の既存 CT エラーは、SSH 接続先の `pct status <vmid>` でローカルの LXC CT の存在を確認できた場合のみ許容します。
VMID はクラスタ全体の QEMU VM と CT で共有されるため、API の `VM <vmid> already exists` は別のリソースを指す場合があります。

継続して失敗する場合は次を確認してください。

- `ct_instance_vmid` が意図した既存 CT と一致しているか
- 新規 CT の VMID が、クラスタ内のすべての VM／CT に対して未使用か。PVE 上の `pvesh get /cluster/resources --type vm` で割り当てを確認できます。`pvesh get /cluster/nextid` は未使用候補を返しますが、ID は予約しません。
- ホスト側パススルーを設定する場合、API 接続先、`ct_instance_node`、inventory の SSH 接続先が同じ PVE ノード・クラスタを指しているか
- 実行環境の Role が最新版か

### トラブルシューティング: CT 内で /dev/nvidia* が見えない

`runtime_vllm` で `/dev/nvidia* missing` が出る場合、CT 側のデバイスパススルー設定が不足しています。

本 Collection では次を推奨します。

```yaml
ct_instance_enable_nvidia_passthrough: true
```

その後 `playbooks/ct_create.yml` を再実行してください。
自動生成では実際のデバイス番号を検出し、標準で `libcuda.so.1` / `libnvidia-ml.so.1` も bind-mount します。全 GPU を公開する場合は `ct_instance_nvidia_gpus: all`、一部だけなら `[0, 2]` のように指定します。既定の `null` は、従来の GPU 0・1 のうち存在するデバイスを公開します。
パススルーブロックが変更された場合は、`ct_instance_restart_on_nvidia_passthrough_change: true` で CT を自動再起動できます。

### トラブルシューティング: CT 内 torch の `CUDA unknown error`

torch probe で `device_count > 0` なのに `is_available=False` かつ `CUDA unknown error` が出る場合、
`/dev/nvidia-uvm` の種別を確認してください。`----------` の通常ファイルになっている場合は、
ホスト側 UVM デバイス生成またはパススルー適用が不完全です。

推奨復旧手順:

1. ホスト GPU 準備 Role を再実行（ホスト側 NVIDIA モジュール/デバイスノードを再整備）。
2. `playbooks/ct_create.yml` を再実行してパススルーと CT 再起動を反映。
3. runtime Playbook を再実行。

### トラブルシューティング: runtime Playbook で apt 404

`ct_runtime_common` のパッケージインストールで Debian の `404 Not Found` が出る場合、CT の apt キャッシュが古い可能性が高いです。
本 Collection はインストール前に apt キャッシュを更新し、失敗時は強制更新して 1 回リトライします。

必要に応じて以下を `group_vars/ct_targets.yml` に設定してください。

```yaml
ct_runtime_common_apt_cache_valid_time: 0
```

毎回 apt キャッシュを更新する動作になります。

### 3) Playbook 実行

```bash
ansible-playbook -i inventory.ini playbooks/host_nvidia_gpu.yml
ansible-playbook -i inventory.ini playbooks/ct_create.yml
ansible-playbook -i inventory.ini playbooks/runtime_vllm.yml
ansible-playbook -i inventory.ini playbooks/validate.yml
```

---

## 必須変数クイックリファレンス（Collection 全体）

> 実運用で指定がほぼ必須となる変数を掲載しています。  
> 全変数は各 Role README を参照してください。

| 変数名 | 概要 | デフォルト値 | 指定可能な値 |
|---|---|---|---|
| `ct_instance_api_host` | Proxmox API ホスト/IP | `{{ inventory_hostname }}` | 有効なホスト名/IP |
| `ct_instance_api_user` | Proxmox API ユーザー | `root@pam` | 有効な PVE API ユーザー |
| `ct_instance_api_token_id` | API Token 名（推奨）または従来形式 `<user>!<token_name>` | `""` | `ci-token`（推奨）または `<user>!<token_name>` |
| `ct_instance_api_token_secret` | API Token Secret | `""` | Token secret 文字列 |
| `ct_instance_validate_certs` | Proxmox API HTTPS 証明書を検証するか | `false` | `true` / `false` |
| `ct_instance_password` | CT root 初期パスワード（任意） | `""` | 空でない文字列（vault 推奨） |
| `ct_instance_pubkey` | CT root 初期公開鍵（任意） | `""` | SSH 公開鍵 1 行 |
| `ct_instance_node` | CT 作成対象ノード | `pve` | 既存ノード名 |
| `ct_instance_vmid` | CT VMID | `100` | 正の整数（クラスタ内一意） |
| `ct_instance_cores` | CT の CPU コア数 | `8` | `1` 以上の整数 |
| `ct_instance_memory` | CT のメモリサイズ (MiB) | `32768` | `512` 以上の整数 |
| `ct_instance_rootfs_size` | CT のディスクサイズ (GiB) | `128` | `8` 以上の整数 |
| `ct_instance_storage` | rootfs 配置ストレージ | `local-lvm` | 既存ストレージ ID |
| `ct_instance_timeout` | Proxmox タスク待機タイムアウト（秒） | `600` | `30` 以上の整数 |
| `ct_instance_enable_nvidia_passthrough` | CT 設定へ NVIDIA パススルーブロックを管理 | `false` | `true` / `false` |
| `ct_instance_nvidia_gpus` | CT に公開するホスト GPU を選択（CT 間の重複指定可） | `null` | `all`、空でない整数リスト、`null` |
| `ct_instance_nvidia_bind_nvidia_smi` | ホストの `nvidia-smi` を CT に読み取り専用で bind-mount | `false` | `true` / `false` |
| `ct_instance_ostemplate` | CT OS テンプレート | Debian 12 template path | 既存 `vztmpl` パス |
| `ct_runtime_vllm_model` | vLLM 配信モデル ID | `mistralai/Mistral-7B-Instruct-v0.3` | 有効な HF/ローカルモデル識別子 |
| `ct_runtime_vllm_hf_token` | vLLM ダウンロード時に使う任意の Hugging Face Token（`HF_TOKEN`） | `""` | 空文字または Token 文字列（vault 推奨） |
| `ct_runtime_vllm_tensor_parallel_size` | Tensor Parallel 数 | `1` | `1` 以上の整数 |
| `ct_runtime_vllm_max_model_len` | LLM コンテキスト長 | `8192` | `1` 以上の整数 |

## オプショナルな共有モデルストレージ

PVE ホストでマウントした NFS を CT に bind mount し、モデルファイルの保存先にできます。
`ct_model_storage_enabled: true` を指定すると、事前作成した namespace のマウント・
実際のファイルシステム種別・runtime user の権限を確認し、サービス起動前にも検証します。
既定では無効で、従来のローカル保存を維持します。

実際の保存先は artifact/component の絶対パスや Hugging Face の hub cache 変数で指定します。
既存ファイルの自動移動は行いません。トークン、venv、sd.cpp のビルド領域、実行時キャッシュは
ローカルに残します。各ランタイムの設定、root squash の権限、新規・既存 CT の接続手順と
実機確認項目は[共有モデルストレージのガイド](docs/shared-model-storage.md)を参照してください。

Role 詳細:

- [`roles/host_gpu_common/README.md`](roles/host_gpu_common/README.md)
- [`roles/host_nvidia_gpu/README.md`](roles/host_nvidia_gpu/README.md)
- [`roles/host_amd_gpu/README.md`](roles/host_amd_gpu/README.md)
- [`roles/ct_instance/README.md`](roles/ct_instance/README.md)
- [`roles/ct_runtime_common/README.md`](roles/ct_runtime_common/README.md)
- [`roles/ct_model_storage/README.md`](roles/ct_model_storage/README.md)
- [`roles/ct_model_artifacts/README.md`](roles/ct_model_artifacts/README.md)
- [`roles/ct_runtime_launcher_common/README.md`](roles/ct_runtime_launcher_common/README.md)
- [`roles/ct_runtime_vllm/README.md`](roles/ct_runtime_vllm/README.md)
- [`roles/ct_runtime_sdcpp/README.md`](roles/ct_runtime_sdcpp/README.md)
- [`roles/ct_runtime_sglang/README.md`](roles/ct_runtime_sglang/README.md)
- [`roles/ct_runtime_tgi/README.md`](roles/ct_runtime_tgi/README.md)
- [`roles/ct_runtime_ollama/README.md`](roles/ct_runtime_ollama/README.md)
- [`roles/ct_validate/README.md`](roles/ct_validate/README.md)

---

## Playbook 一覧

- `playbooks/host_nvidia_gpu.yml`
- `playbooks/host_amd_gpu.yml`
- `playbooks/ct_create.yml`
- `playbooks/runtime_vllm.yml`
- `playbooks/runtime_sdcpp.yml`
- `playbooks/runtime_sglang.yml`
- `playbooks/runtime_tgi.yml`
- `playbooks/runtime_ollama.yml`
- `playbooks/validate.yml`

---

## ライセンス

MIT

## vLLM: STT・話者分離・画像/動画生成

`ct_runtime_vllm` は通常の vLLM による文字起こし・対応モデルでの話者分離付き文字起こし、
vLLM-Omni による画像/動画生成を選択できます。最新版の更新設定、モデル別の変数と API 利用例は
[Role README](roles/ct_runtime_vllm/README.md#deploying-audio-image-and-video-models) を参照してください。
画像/動画生成には Omni と対応する GPU・Python・CUDA 環境が必要です。

STT 用と画像生成用の CT で同じホスト GPU を共有する構成は、
[共有 GPU のデプロイ例](examples/shared-nvidia/README.md)を参照してください。

## stable-diffusion.cpp: native 画像 API バックエンド

`ct_runtime_sdcpp` は commit を固定した native `sd-server` をビルドし、GPU を利用できる
既存 CT 上で独立した systemd service を管理します。ユーザー・ディレクトリとモデルファイルの
準備を再利用し、runtime 用 Python venv や LLM launcher 設定は使用しません。
PVE host driver の変更、CT 作成、既存 vLLM service の停止は行いません。

[デプロイ・受入手順](docs/sdcpp-deployment.md)、
[P-H3 W4A8/INT8 example](examples/sdcpp/README.md)、
[Role 変数](roles/ct_runtime_sdcpp/README.md)を参照してください。
Example は model revision と SHA256 を固定し、4 GPU の layer 分割を指定します。
VRAM の均等使用や、LLM 向けの容量予約は保証しません。

ビルド並列数の既定値は `2` です。`ct_runtime_sdcpp_build_jobs: auto` で CT 内の
ビルドユーザーが利用可能な CPU 数を使い、正整数の指定でメモリ・CPU 使用を抑えられます。
Role は選択した並列数をログに表示し、この値だけの変更ではビルドキャッシュを維持します。
詳細は[ビルド並列数](roles/ct_runtime_sdcpp/README.md#build-parallelism)を参照してください。

Service の `PrivateTmp` は選択制で、既定値は `ct_runtime_sdcpp_private_tmp: false` です。
LXC の制限によっては、実行前の mount namespace 作成が `226/NAMESPACE` で失敗します。
該当時は[復旧手順](docs/sdcpp-deployment.md#recover-from-226namespace)を参照してください。

**実装の方向性は承認済みですが、設計の最終確定は実機デプロイ試験後です。**
[ADR-006](adr/adr-006-sdcpp-runtime.md) は、CUDA build、モデルの生成・編集、GPU ごとの
メモリ使用量、LLM との同居、再実行・復旧の結果を記録するまで Proposed として扱います。
ローカルのコード検査と実機試験の結果を区別します。
