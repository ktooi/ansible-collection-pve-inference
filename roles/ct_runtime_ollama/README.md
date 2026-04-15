# Role: ct_runtime_ollama

## Purpose
Placeholder role for future Ollama runtime integration.

## Usage
```yaml
- hosts: ct_targets
  become: true
  roles:
    - role: ktooi.pve_inference.ct_runtime_ollama
```

## Variables

| Variable | Description | Default | Allowed values |
|---|---|---|---|
| `role_enabled` | Toggle scaffold message behavior | `false` | `true` / `false` |
