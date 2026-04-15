# Role: ct_runtime_tgi

## Purpose
Placeholder role for future TGI runtime integration.

## Usage
```yaml
- hosts: ct_targets
  become: true
  roles:
    - role: ktooi.pve_inference.ct_runtime_tgi
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `role_enabled` | Toggle scaffold message behavior | `false` | `true` / `false` |
