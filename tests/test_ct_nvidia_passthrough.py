"""Test device inspection and real Ansible rendering with read-only device symlinks.

No NVIDIA hardware, mknod privileges, Proxmox API, or container restart is used.
"""

import copy
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles/ct_instance'
spec = importlib.util.spec_from_file_location('nvidia_device_info', ROOT / 'plugins/modules/nvidia_device_info.py')
device_info = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device_info)


def make_devices(root):
    root.mkdir()
    for number, target in enumerate(['/dev/null', '/dev/zero', '/dev/full', '/dev/urandom']):
        (root / f'nvidia{number}').symlink_to(target)
    (root / 'nvidiactl').symlink_to('/dev/random')
    (root / 'nvidia-uvm').symlink_to('/dev/tty')
    return root


class DeviceInfoTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='ct-nvidia-devices-')
        self.addCleanup(self.directory.cleanup)
        self.devices = make_devices(Path(self.directory.name) / 'dev')

    def inspect(self, gpus=None):
        return device_info.inspect_devices(gpus, str(self.devices))

    def test_all_selects_available_character_devices_in_numeric_order(self):
        (self.devices / 'nvidia10').symlink_to('/dev/full')
        (self.devices / 'nvidia4').touch()
        result = self.inspect('all')
        self.assertEqual(result['selected_gpus'], [0, 1, 2, 3, 10])
        self.assertEqual(result['available_gpus'], [0, 1, 2, 3, 10])

    def test_subset_excludes_other_gpu_minor_permissions(self):
        result = self.inspect([3, 1])
        self.assertEqual(result['selected_gpus'], [1, 3])
        names = [node['name'] for node in result['device_nodes']]
        self.assertEqual(names, ['nvidia1', 'nvidia3', 'nvidiactl', 'nvidia-uvm'])
        pairs = {(node['major'], node['minor']) for node in result['cgroup_devices']}
        for excluded in ['nvidia0', 'nvidia2']:
            info = (self.devices / excluded).stat()
            self.assertNotIn((os.major(info.st_rdev), os.minor(info.st_rdev)), pairs)
        info = (self.devices / 'nvidia-uvm').stat()
        self.assertIn((os.major(info.st_rdev), os.minor(info.st_rdev)), pairs)

    def test_default_keeps_available_legacy_nodes(self):
        self.assertEqual(self.inspect()['selected_gpus'], [0, 1])
        (self.devices / 'nvidia1').unlink()
        self.assertEqual(self.inspect()['selected_gpus'], [0])

    def test_all_requires_at_least_one_available_gpu(self):
        for number in range(4):
            (self.devices / f'nvidia{number}').unlink()
        with self.assertRaisesRegex(ValueError, 'missing or not character'):
            self.inspect('all')

    def test_invalid_selectors_are_rejected(self):
        for value in [[], '', '0', 'ALL', True, 0, {}, [-1], [True], ['0'], [0, 0], [0.5], [{}]]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'gpus must be'):
                self.inspect(value)

    def test_missing_and_regular_gpu_nodes_are_rejected(self):
        for value in [[99], [0, 99]]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'missing or not character'):
                self.inspect(value)
        (self.devices / 'nvidia2').unlink()
        (self.devices / 'nvidia2').touch()
        with self.assertRaisesRegex(ValueError, 'missing or not character'):
            self.inspect([2])

    def test_control_and_uvm_are_required(self):
        for name in ['nvidiactl', 'nvidia-uvm']:
            path = self.devices / name
            target = path.readlink()
            path.unlink()
            with self.subTest(name=name), self.assertRaises(OSError):
                self.inspect('all')
            path.symlink_to(target)
        (self.devices / 'nvidia-uvm').unlink()
        (self.devices / 'nvidia-uvm').touch()
        with self.assertRaisesRegex(ValueError, 'not a character device'):
            self.inspect('all')

    def test_capability_devices_are_deduplicated_and_optional(self):
        self.assertIsNone(self.inspect('all')['caps_directory'])
        caps = self.devices / 'nvidia-caps'
        caps.mkdir()
        (caps / 'nvidia-cap1').symlink_to('/dev/tty')
        (self.devices / 'nvidia-uvm-tools').symlink_to('/dev/ptmx')
        (self.devices / 'nvidia-modeset').symlink_to('/dev/ptmx')
        result = self.inspect('all')
        self.assertEqual(result['caps_directory'], str(caps))
        pairs = [(node['major'], node['minor']) for node in result['cgroup_devices']]
        self.assertEqual(len(pairs), len(set(pairs)))


class PassthroughRoleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='ct-nvidia-role-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.devices = make_devices(self.root / 'dev')
        self.config = self.root / '120.conf'
        self.config.write_text('hostname: preserved\n')
        collection = self.root / 'collections/ansible_collections/ktooi/pve_inference'
        collection.parent.mkdir(parents=True)
        collection.symlink_to(ROOT, target_is_directory=True)

    def generate(self, **values):
        return {'ansible.builtin.include_role': {
            'name': 'ktooi.pve_inference.ct_instance', 'tasks_from': 'nvidia_passthrough.yml',
        }, 'vars': values}

    def persist(self, path=None):
        source = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        task = copy.deepcopy(next(task for task in source if task.get('name') ==
                                  'Configure NVIDIA device passthrough in LXC config'))
        task['ansible.builtin.blockinfile']['path'] = str(path or self.config)
        return task

    def run_tasks(self, tasks, overrides=None, check=False, missing_devices=False):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        values = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        values.update(ct_instance_enable_nvidia_passthrough=True,
                      ansible_python_interpreter=os.sys.executable, ansible_become=False)
        values.update(overrides or {})
        playbook = self.root / 'test.yml'
        playbook.write_text(yaml.safe_dump([{
            'hosts': 'localhost', 'gather_facts': False, 'vars': values,
            'module_defaults': {'ktooi.pve_inference.nvidia_device_info': {
                'path': str(self.root / 'missing' if missing_devices else self.devices),
            }},
            'tasks': tasks,
        }], sort_keys=False))
        result = subprocess.run(
            [executable, '-i', 'localhost,', '-c', 'local', *(['--check'] if check else []), str(playbook)],
            env=dict(os.environ, ANSIBLE_NOCOLOR='1',
                     ANSIBLE_HOME=str(self.root / 'ansible-home'),
                     ANSIBLE_LOCAL_TEMP=str(self.root / 'tmp'),
                     ANSIBLE_COLLECTIONS_PATH=str(self.root / 'collections')),
            text=True, capture_output=True, timeout=60,
        )
        return result.returncode, result.stdout + result.stderr

    def test_all_gpus_can_be_shared_by_two_cts_idempotently(self):
        second = self.root / '121.conf'
        second.write_text('hostname: second\n')
        tasks = []
        for path in [self.config, second]:
            tasks += [self.generate(ct_instance_nvidia_gpus='all'), self.persist(path)]
        for path in [self.config, second]:
            tasks += [self.generate(ct_instance_nvidia_gpus='all'), self.persist(path),
                      {'ansible.builtin.assert': {'that': ['not ct_instance_nvidia_passthrough_result.changed']}}]
        status, output = self.run_tasks(tasks)
        self.assertEqual(status, 0, output)
        for path in [self.config, second]:
            text = path.read_text()
            for number in range(4):
                self.assertEqual(text.count(f' dev/nvidia{number} '), 1)
            self.assertNotIn(':* rwm', text)
        self.assertTrue(self.config.read_text().startswith('hostname: preserved\n'))

    def test_selection_changes_replace_old_mounts_and_refresh_per_ct_facts(self):
        tasks = [self.generate(ct_instance_nvidia_gpus='all'), self.persist(),
                 self.generate(ct_instance_nvidia_gpus=[3, 1]), self.persist()]
        status, output = self.run_tasks(tasks)
        self.assertEqual(status, 0, output)
        text = self.config.read_text()
        for number in [1, 3]:
            self.assertIn(f' dev/nvidia{number} ', text)
        for number in [0, 2]:
            self.assertNotIn(f' dev/nvidia{number} ', text)

    def test_default_handles_a_single_gpu_host(self):
        for number in [1, 2, 3]:
            (self.devices / f'nvidia{number}').unlink()
        status, output = self.run_tasks([self.generate(), self.persist()])
        self.assertEqual(status, 0, output)
        text = self.config.read_text()
        self.assertIn(' dev/nvidia0 ', text)
        self.assertNotIn(' dev/nvidia1 ', text)

    def test_automatic_generation_replaces_a_previous_raw_override(self):
        raw = 'lxc.cgroup2.devices.allow: c 222:7 rwm'
        status, output = self.run_tasks([
            self.generate(ct_instance_nvidia_passthrough_block=raw), self.persist(),
            self.generate(ct_instance_nvidia_gpus=[2]), self.persist(),
        ])
        self.assertEqual(status, 0, output)
        text = self.config.read_text()
        self.assertNotIn(raw, text)
        self.assertIn(' dev/nvidia2 ', text)

    def test_raw_override_bypasses_discovery_and_feature_generation(self):
        raw = 'lxc.cgroup2.devices.allow: c 222:7 rwm\nlxc.mount.entry: /custom dev/custom none bind,create=file'
        status, output = self.run_tasks([
            self.generate(ct_instance_nvidia_gpus=True, ct_instance_nvidia_passthrough_block=raw,
                          ct_instance_nvidia_mount_host_cuda_toolkit=True,
                          ct_instance_nvidia_bind_nvidia_smi=True), self.persist(),
        ], missing_devices=True)
        self.assertEqual(status, 0, output)
        text = self.config.read_text()
        self.assertIn(raw, text)
        self.assertNotIn('libcuda', text)
        self.assertNotIn('/usr/local/cuda', text)

    def test_host_nvidia_smi_bind_is_opt_in_and_read_only(self):
        binary = self.root / 'nvidia-smi'
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o755)
        status, output = self.run_tasks([
            self.generate(), self.persist(),
        ])
        self.assertEqual(status, 0, output)
        self.assertNotIn('usr/bin/nvidia-smi', self.config.read_text())
        status, output = self.run_tasks([
            self.generate(ct_instance_nvidia_bind_nvidia_smi=True,
                          ct_instance_host_nvidia_smi_path=str(binary)), self.persist(),
        ])
        self.assertEqual(status, 0, output)
        self.assertIn(f'{binary} usr/bin/nvidia-smi none bind,ro,create=file', self.config.read_text())

    def test_missing_or_nonexecutable_host_nvidia_smi_stops_before_writing(self):
        for present in [False, True]:
            binary = self.root / 'nvidia-smi'
            if present:
                binary.write_text('not executable\n')
                binary.chmod(0o644)
            with self.subTest(present=present):
                status, output = self.run_tasks([
                    self.generate(ct_instance_nvidia_bind_nvidia_smi=True,
                                  ct_instance_host_nvidia_smi_path=str(binary)), self.persist(),
                ])
                self.assertEqual(status, 2, output)
                self.assertIn('requires an executable host nvidia-smi', output)
                self.assertEqual(self.config.read_text(), 'hostname: preserved\n')

    def test_cuda_feature_flags_are_preserved(self):
        status, output = self.run_tasks([
            self.generate(ct_instance_nvidia_gpus=[0], ct_instance_nvidia_bind_driver_libraries=False,
                          ct_instance_nvidia_mount_host_cuda_toolkit=True,
                          ct_instance_host_cuda_toolkit_path='/usr/local/cuda-13.5'), self.persist(),
        ])
        self.assertEqual(status, 0, output)
        text = self.config.read_text()
        self.assertNotIn('libcuda.so', text)
        self.assertIn('/usr/local/cuda-13.5 usr/local/cuda-13.5', text)
        self.assertIn('/usr/local/cuda-13.5 usr/local/nvidia', text)

    def test_missing_gpu_fails_before_writing_configuration(self):
        status, output = self.run_tasks([self.generate(ct_instance_nvidia_gpus=[99]), self.persist()])
        self.assertEqual(status, 2, output)
        self.assertIn('missing or not character devices', output)
        self.assertEqual(self.config.read_text(), 'hostname: preserved\n')

    def test_disabled_and_absent_cts_skip_device_discovery(self):
        for values in [{'ct_instance_enable_nvidia_passthrough': False}, {'ct_instance_state': 'absent'}]:
            with self.subTest(values=values):
                status, output = self.run_tasks([self.generate(), self.persist()], values, missing_devices=True)
                self.assertEqual(status, 0, output)
                self.assertEqual(self.config.read_text(), 'hostname: preserved\n')

    def test_check_mode_inspects_devices_without_writing_configuration(self):
        status, output = self.run_tasks([
            self.generate(ct_instance_nvidia_gpus='all'), self.persist(),
            {'ansible.builtin.assert': {'that': ['not ct_instance_nvidia_devices.changed']}},
        ], check=True)
        self.assertEqual(status, 0, output)
        self.assertEqual(self.config.read_text(), 'hostname: preserved\n')


if __name__ == '__main__':
    unittest.main()
