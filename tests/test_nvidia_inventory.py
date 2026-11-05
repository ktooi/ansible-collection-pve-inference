"""Exercise NVML error streams and expected-GPU-count checks without hardware."""

import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'host_nvidia_gpu'


class InventoryTests(unittest.TestCase):
    def task(self, name):
        source = yaml.safe_load((ROLE / 'tasks' / 'main.yml').read_text())
        return copy.deepcopy(next(task for task in source if task.get('name') == name))

    def run_tasks(self, tasks, variables):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        with tempfile.TemporaryDirectory(prefix='nvidia-inventory-') as directory:
            root = Path(directory)
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump([{
                'hosts': 'localhost', 'gather_facts': False,
                'vars': variables, 'tasks': tasks,
            }], sort_keys=False))
            result = subprocess.run(
                [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                env=dict(os.environ, ANSIBLE_NOCOLOR='1',
                         ANSIBLE_HOME=str(root / 'ansible-home'),
                         ANSIBLE_LOCAL_TEMP=str(root / 'tmp')),
                text=True, capture_output=True, timeout=60,
            )
            return result.returncode, result.stdout + result.stderr

    def test_nvml_mismatch_in_either_stream_is_detected(self):
        message = 'Failed to initialize NVML: Driver/library version mismatch'
        cases = [
            ({'rc': 1, 'stdout': '', 'stderr': message}, True),
            ({'rc': 1, 'stdout': message, 'stderr': ''}, True),
            ({'rc': 1, 'stdout': '', 'stderr': 'No devices were found'}, False),
            ({'rc': 0, 'stdout': 'GPU 0: RTX 3090', 'stderr': ''}, False),
        ]
        tasks = []
        for probe, expected in cases:
            detect = self.task('Derive NVML mismatch fact from nvidia-smi probe')
            detect['vars'] = {'host_nvidia_gpu_pre_persistenced_smi': probe}
            tasks.append(detect)
            tasks.append({'ansible.builtin.assert': {
                'that': [f'host_nvidia_gpu_nvml_mismatch_detected == {str(expected).lower()}'],
            }})
        status, output = self.run_tasks(tasks, {'host_nvidia_gpu_enable_persistenced': True})
        self.assertEqual(status, 0, output)

    def test_expected_count_checks_physical_gpu_lines(self):
        cases = [
            (4, ['GPU 0: RTX 3090', 'GPU 1: RTX 3090', 'GPU 2: RTX 3090', 'GPU 3: RTX 3090'], 0, 4),
            (4, ['GPU 0: RTX 3090'], 2, 1),
            (0, ['GPU 0: RTX 3090'], 0, 1),
            (2, ['GPU 0: GPU', '  MIG child device', 'GPU 1: GPU', '  MIG child device'], 0, 2),
        ]
        for expected, lines, expected_status, count in cases:
            with self.subTest(expected=expected, lines=lines):
                tasks = [self.task(name) for name in [
                    'Validate expected NVIDIA GPU count setting',
                    'Count GPUs enumerated by nvidia-smi',
                    'Require the configured NVIDIA GPU count',
                ]]
                tasks.append({'ansible.builtin.assert': {
                    'that': [f'host_nvidia_gpu_visible_gpu_count | int == {count}'],
                }})
                status, output = self.run_tasks(tasks, {
                    'host_nvidia_gpu_expected_gpu_count': expected,
                    'nvidia_smi_devices': {'stdout_lines': lines, 'stdout': '\n'.join(lines)},
                })
                self.assertEqual(status, expected_status, output)
                if expected_status:
                    self.assertIn('Expected 4 NVIDIA GPUs', output)
                    self.assertIn('enumerated 1', output)

    def test_invalid_count_is_rejected(self):
        for value in [-1, 'four', True]:
            with self.subTest(value=value):
                status, output = self.run_tasks([
                    self.task('Validate expected NVIDIA GPU count setting'),
                ], {'host_nvidia_gpu_expected_gpu_count': value})
                self.assertEqual(status, 2, output)
                self.assertIn('non-negative integer', output)


if __name__ == '__main__':
    unittest.main()
