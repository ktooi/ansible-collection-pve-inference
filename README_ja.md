# ktooi.pve_inference

**Proxmox VE 上の CT ベース推論環境**を構築・運用するための Ansible Collection です。

このプロジェクトは、宣言的な運用と責務分離を重視しています。
- **PVE ホスト側**: GPU 利用前提やホスト設定を担当
- **CT 側**: 共通ランタイム基盤、推論ランタイム導入、systemd サービス管理を担当

## スコープ

### 含むもの
- ホスト側 GPU 前提設定
- CT の宣言的ライフサイクル管理（作成/更新/削除）
- CT 内共通基盤（Python、各種ディレクトリ、サービス前提）
- ランタイム別 Role（初期は vLLM）
- 構築後検証とヘルスチェック

### 初期フェーズで含まないもの
- Kubernetes オーケストレーション
- VM 主体の運用
- 複数ノード分散推論の本格オーケストレーション
- Docker/Podman ネスト運用の主対応

## サポート方針（要約）
- **Proxmox VE 8.x**: 正規サポート
- **Proxmox VE 9.x**: ベータサポート
- 初期対象: **NVIDIA + vLLM**
- 将来の **AMD** および他ランタイム拡張を前提とした構造

詳細は `docs/support-policy.md`、`docs/gpu-matrix.md`、`docs/runtime-matrix.md` を参照してください。

## Collection 構成

```text
ktooi.pve_inference/
  galaxy.yml
  meta/runtime.yml
  docs/
  playbooks/
  roles/
  plugins/
  tests/
```

## Role 一覧

- `host_gpu_common`
- `host_nvidia_gpu`
- `host_amd_gpu`（将来実装用の雛形）
- `ct_instance`
- `ct_runtime_common`
- `ct_runtime_vllm`
- `ct_runtime_sglang`（雛形）
- `ct_runtime_tgi`（雛形）
- `ct_runtime_ollama`（雛形）
- `ct_validate`

## 基本フロー

1. PVE ホストを GPU 利用可能にする
2. CT を作成/更新する
3. CT の共通ランタイム基盤を整備する
4. 推論ランタイムを導入する
5. 動作確認を行う

## 要件

- Ansible Core `>=2.16`
- 依存 Collection:
  - `community.proxmox >=1.6.0`

依存インストール:

```bash
ansible-galaxy collection install -r requirements.yml
```

`requirements.yml` 例:

```yaml
collections:
  - name: community.proxmox
    version: ">=1.6.0"
```

## 実行例

```bash
ansible-playbook playbooks/host_nvidia_gpu.yml -i inventory.ini
ansible-playbook playbooks/ct_create.yml -i inventory.ini
ansible-playbook playbooks/runtime_vllm.yml -i inventory.ini
ansible-playbook playbooks/validate.yml -i inventory.ini
```

## 設計メモ

- ランタイム差分は `ct_runtime_*` Role に分離
- GPU ベンダ差分は `host_*` Role に分離
- CT ライフサイクルは `ct_instance` で独立管理
- 初期は systemd による直実行を優先し、トラブルシュート容易性を重視

## 現在の状態

本リポジトリは、単一ノード初期導入を想定した拡張可能なベースラインを提供します。

## ライセンス

MIT
