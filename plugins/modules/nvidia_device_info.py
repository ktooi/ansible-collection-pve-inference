#!/usr/bin/python
# Copyright: (c) 2026, ktooi
# SPDX-License-Identifier: MIT

DOCUMENTATION = r'''
---
module: nvidia_device_info
short_description: Inspect NVIDIA character devices for CT passthrough
version_added: '0.1.0'
description:
  - Read NVIDIA device nodes without loading modules or creating devices.
  - Return exact character-device major/minor pairs for selected GPU nodes and common control devices.
options:
  gpus:
    description:
      - Use C(all) for every available GPU, or a non-empty list of non-negative integers.
      - Numbers refer to the host C(/dev/nvidiaN) suffix, not container-local CUDA ordinals.
      - An omitted or null value selects available nodes numbered 0 and 1 for compatibility.
    type: raw
  path:
    description: Directory containing the NVIDIA device nodes.
    type: path
    default: /dev
attributes:
  check_mode:
    support: full
author:
  - ktooi
'''

EXAMPLES = r'''
- name: Inspect all GPUs before generating CT configuration
  ktooi.pve_inference.nvidia_device_info:
    gpus: all
  register: nvidia_devices

- name: Inspect a subset that another CT may also share
  ktooi.pve_inference.nvidia_device_info:
    gpus: [0, 2]
'''

RETURN = r'''
available_gpus:
  description: Available host GPU node numbers.
  returned: success
  type: list
  elements: int
selected_gpus:
  description: Selected host GPU node numbers, sorted numerically.
  returned: success
  type: list
  elements: int
device_nodes:
  description: Selected GPU and common device nodes, with name, path, major, and minor.
  returned: success
  type: list
  elements: dict
cgroup_devices:
  description: Unique major/minor pairs, including NVIDIA capability devices if present.
  returned: success
  type: list
  elements: dict
caps_directory:
  description: Capability directory path, or null when absent.
  returned: success
  type: str
'''

from pathlib import Path
import os
import re
import stat

from ansible.module_utils.basic import AnsibleModule


def device_record(path, name):
    info = path.stat()
    if not stat.S_ISCHR(info.st_mode):
        raise ValueError("NVIDIA device is not a character device: %s" % path)
    return dict(name=name, path=str(path), major=os.major(info.st_rdev), minor=os.minor(info.st_rdev))


def inspect_devices(gpus=None, path='/dev'):
    if gpus is not None and gpus != 'all':
        if (not isinstance(gpus, list) or not gpus
                or any(type(number) is not int or number < 0 for number in gpus)
                or len(gpus) != len(set(gpus))):
            raise ValueError("gpus must be 'all', a non-empty list of unique non-negative integers, or null")

    root = Path(path)
    available = {}
    for node in root.iterdir():
        match = re.fullmatch(r'nvidia([0-9]+)', node.name)
        if match and node.is_char_device():
            available[int(match.group(1))] = device_record(node, node.name)
    selected = sorted(available if gpus == 'all' else
                      [number for number in (gpus if gpus is not None else [0, 1])
                       if number in available])
    missing = sorted(set(gpus or []) - set(available)) if isinstance(gpus, list) else []
    if missing or not selected:
        raise ValueError(
            'Requested NVIDIA GPU nodes are missing or not character devices. '
            'Requested: %s; missing: %s; available: %s. Prepare host NVIDIA devices first.'
            % (gpus if gpus is not None else [0, 1], missing, sorted(available)))

    nodes = [available[number] for number in selected]
    for name in ('nvidiactl', 'nvidia-uvm', 'nvidia-uvm-tools', 'nvidia-modeset'):
        node = root / name
        if name in ('nvidiactl', 'nvidia-uvm') or node.exists():
            nodes.append(device_record(node, name))

    caps = root / 'nvidia-caps'
    capabilities = []
    if caps.exists():
        if not caps.is_dir():
            raise ValueError('NVIDIA capability path is not a directory: %s' % caps)
        capabilities = [device_record(node, str(node.relative_to(root)))
                        for node in sorted(caps.rglob('*')) if node.is_char_device()]
    pairs = sorted({(node['major'], node['minor']) for node in nodes + capabilities})
    return dict(available_gpus=sorted(available), selected_gpus=selected,
                device_nodes=nodes, caps_directory=str(caps) if caps.is_dir() else None,
                cgroup_devices=[dict(major=major, minor=minor) for major, minor in pairs])


def main():
    module = AnsibleModule(argument_spec=dict(gpus=dict(type='raw'), path=dict(type='path', default='/dev')),
                           supports_check_mode=True)
    try:
        result = inspect_devices(module.params['gpus'], module.params['path'])
    except (OSError, ValueError) as error:
        module.fail_json(msg=str(error))
    module.exit_json(changed=False, **result)


if __name__ == '__main__':
    main()
