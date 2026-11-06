"""Validate declarative model assets without exposing their source URLs."""

import math
import posixpath
import re
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit

from ansible.errors import AnsibleFilterError


def _list(value, label):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AnsibleFilterError(label + " must be a list.")


def _path(value, label):
    if (not isinstance(value, str) or not value.startswith("/")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or ".." in value.split("/")):
        raise AnsibleFilterError(label + " must be an absolute path without parent traversal or control characters.")
    normalized = "/" + posixpath.normpath(value).lstrip("/")
    if normalized == "/" or value.endswith("/"):
        raise AnsibleFilterError(label + " must identify a file or adapter directory, not the filesystem root.")
    return normalized


def model_artifacts_validate(value):
    _list(value, "ct_model_artifacts")
    result, destinations = [], set()
    for index, item in enumerate(value):
        label = "Model artifact #" + str(index + 1)
        if not isinstance(item, Mapping) or set(item) - {"name", "url", "dest", "checksum", "headers"}:
            raise AnsibleFilterError(label + " must contain only name, url, dest, checksum and optional headers.")
        url = item.get("url")
        try:
            parsed = urlsplit(url) if isinstance(url, str) else None
        except ValueError:
            parsed = None
        if (parsed is None or parsed.scheme not in ("https", "http") or not parsed.hostname
                or any(char.isspace() or ord(char) < 32 for char in url)):
            raise AnsibleFilterError(label + " requires an HTTP(S) URL.")
        destination = _path(item.get("dest"), label + " destination")
        if destination in destinations:
            raise AnsibleFilterError("Model artifact destinations must be unique.")
        destinations.add(destination)
        checksum = item.get("checksum")
        if not isinstance(checksum, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", checksum):
            raise AnsibleFilterError(label + " requires a pinned sha256 checksum.")
        name = item.get("name", posixpath.basename(destination))
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name):
            raise AnsibleFilterError(label + " name must be a non-empty local alias using letters, numbers, dots, underscores or hyphens.")
        headers = item.get("headers", {})
        if (not isinstance(headers, Mapping)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items())):
            raise AnsibleFilterError(label + " headers must map strings to strings.")
        result.append({"name": name, "url": url, "dest": destination,
                       "checksum": checksum.lower(), "headers": headers})
    return result


def vllm_lora_adapters_validate(value, backend):
    _list(value, "ct_runtime_vllm_lora_adapters")
    if backend not in ("core", "omni"):
        raise AnsibleFilterError("LoRA backend must be core or omni.")
    result, names = [], set()
    for index, item in enumerate(value):
        label = "LoRA adapter #" + str(index + 1)
        if not isinstance(item, Mapping) or set(item) - {"name", "path", "scale"}:
            raise AnsibleFilterError(label + " must contain name, path and optional Omni scale.")
        name = item.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", name):
            raise AnsibleFilterError(label + " requires a non-empty local alias.")
        if name in names:
            raise AnsibleFilterError("LoRA adapter aliases must be unique.")
        names.add(name)
        path = _path(item.get("path"), label + " path")
        if backend == "core" and not re.fullmatch(r"/[A-Za-z0-9_./-]+", path):
            raise AnsibleFilterError("Core LoRA paths must use letters, numbers, slashes, dots, underscores or hyphens.")
        adapter = {"name": name, "path": path}
        if backend == "core" and "scale" in item:
            raise AnsibleFilterError("Request-level scale is supported only by Omni.")
        if backend == "omni":
            scale = item.get("scale", 1.0)
            try:
                valid_scale = (not isinstance(scale, bool) and isinstance(scale, (int, float))
                               and math.isfinite(scale) and scale >= 0)
            except OverflowError:
                valid_scale = False
            if not valid_scale:
                raise AnsibleFilterError(label + " scale must be a finite non-negative number.")
            adapter["scale"] = float(scale)
        result.append(adapter)
    return result


def vllm_lora_requests(value):
    return {item["name"]: {"name": item["name"], "local_path": item["path"], "scale": item.get("scale", 1.0)}
            for item in value}


class FilterModule:
    def filters(self):
        return {"model_artifacts_validate": model_artifacts_validate,
                "vllm_lora_adapters_validate": vllm_lora_adapters_validate,
                "vllm_lora_requests": vllm_lora_requests}
