"""Run the real nvcc probe tasks against controlled PATH fixtures, without CUDA."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'host_nvidia_gpu'


class NvccProbeTests(unittest.TestCase):
    def check_probe(self, present):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        with tempfile.TemporaryDirectory(prefix='nvidia-nvcc-probe-') as directory:
            root = Path(directory)
            binary = root / 'nvcc'
            if present:
                binary.write_text('#!/bin/sh\nexit 0\n')
                binary.chmod(0o755)
            names = ['Probe nvcc on host', 'Re-probe nvcc on host after toolkit install attempt']
            source = yaml.safe_load((ROLE / 'tasks' / 'main.yml').read_text())
            tasks = [task for task in source if task.get('name') in names]
            self.assertEqual(len(tasks), 2)
            tasks.append({'name': 'Verify real probe results', 'ansible.builtin.assert': {
                'that': [
                    f'host_nvidia_gpu_nvcc_path.rc {"== 0" if present else "!= 0"}',
                    f'host_nvidia_gpu_nvcc_path_after.rc {"== 0" if present else "!= 0"}',
                    f'host_nvidia_gpu_nvcc_path.stdout == {str(binary) if present else ""!r}',
                    f'host_nvidia_gpu_nvcc_path_after.stdout == {str(binary) if present else ""!r}',
                ],
            }})
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump([{
                'hosts': 'localhost', 'gather_facts': False,
                'vars': {'ansible_python_interpreter': os.sys.executable,
                         'host_nvidia_gpu_install_cuda_toolkit': True},
                'environment': {'PATH': str(root)},
                'tasks': tasks,
            }], sort_keys=False))
            env = dict(os.environ, ANSIBLE_NOCOLOR='1',
                       ANSIBLE_HOME=str(root / 'ansible-home'),
                       ANSIBLE_LOCAL_TEMP=str(root / 'tmp'))
            result = subprocess.run(
                [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                env=env, text=True, capture_output=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_existing_nvcc_is_found_without_an_external_command_executable(self):
        self.check_probe(True)

    def test_missing_nvcc_returns_the_expected_not_found_status(self):
        self.check_probe(False)


if __name__ == '__main__':
    unittest.main()
