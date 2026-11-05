"""Exercise package preconditions and error propagation without package changes."""

import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'host_nvidia_gpu'
FAIL_APT = '''
from ansible.module_utils.basic import AnsibleModule
module = AnsibleModule(argument_spec={
    'name': {'type': 'raw'}, 'state': {'type': 'str'},
    'update_cache': {'type': 'bool'}, 'default_release': {'type': 'str'},
})
module.fail_json(msg='Toolkit package installation failed: interrupted dpkg transaction', rc=100)
'''


class PackageStateTests(unittest.TestCase):
    def run_tasks(self, tasks, variables=None):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        with tempfile.TemporaryDirectory(prefix='nvidia-package-state-') as directory:
            root = Path(directory)
            (root / 'library').mkdir()
            (root / 'library' / 'fixture_apt.py').write_text(FAIL_APT)
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump([{
                'hosts': 'localhost', 'gather_facts': False,
                'vars': {'ansible_python_interpreter': os.sys.executable, **(variables or {})},
                'tasks': tasks + [{'name': 'Reach package follow-up',
                                   'ansible.builtin.debug': {'msg': 'PACKAGE_FOLLOW_UP_REACHED'}}],
            }], sort_keys=False))
            env = dict(os.environ, ANSIBLE_NOCOLOR='1',
                       ANSIBLE_HOME=str(root / 'ansible-home'),
                       ANSIBLE_LOCAL_TEMP=str(root / 'tmp'),
                       ANSIBLE_LIBRARY=str(root / 'library'))
            result = subprocess.run(
                [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                env=env, text=True, capture_output=True, timeout=60,
            )
            return result.returncode, result.stdout + result.stderr

    def preflight(self, audit):
        tasks = yaml.safe_load((ROLE / 'tasks' / 'package_preflight.yml').read_text())
        # Replace only dpkg I/O, preserving the real command module and assert.
        tasks[0]['ansible.builtin.command']['argv'] = [
            os.sys.executable, '-c', 'import sys; print(sys.argv[1], end="")', audit,
        ]
        return self.run_tasks(tasks)

    def test_unconfigured_packages_stop_before_follow_up(self):
        status, output = self.preflight('Unpacked but not configured: cuda-nvcc-13-5')
        self.assertEqual(status, 2, output)
        self.assertIn('cuda-nvcc-13-5', output)
        self.assertIn('reviewed repair', output)
        self.assertNotIn('PACKAGE_FOLLOW_UP_REACHED', output)

    def test_consistent_package_state_continues(self):
        status, output = self.preflight('')
        self.assertEqual(status, 0, output)
        self.assertIn('PACKAGE_FOLLOW_UP_REACHED', output)

    def test_toolkit_apt_errors_abort_even_when_compiler_check_is_relaxed(self):
        source = yaml.safe_load((ROLE / 'tasks' / 'main.yml').read_text())
        task = next(item for item in source
                    if item.get('name') == 'Install host CUDA toolkit packages when nvcc is missing (optional)')
        fixture = copy.deepcopy(task)
        fixture['ansible.legacy.fixture_apt'] = fixture.pop('ansible.builtin.apt')
        for strict in [False, True]:
            with self.subTest(strict=strict):
                status, output = self.run_tasks([fixture], {
                    'host_nvidia_gpu_install_cuda_toolkit': True,
                    'host_nvidia_gpu_require_nvcc_when_toolkit_enabled': strict,
                    'host_nvidia_gpu_nvcc_path': {'rc': 1},
                    'host_nvidia_gpu_cuda_toolkit_packages': ['cuda-toolkit-13-5'],
                    'host_nvidia_gpu_apt_default_release': '',
                })
                self.assertEqual(status, 2, output)
                self.assertIn('interrupted dpkg transaction', output)
                self.assertNotIn('PACKAGE_FOLLOW_UP_REACHED', output)


if __name__ == '__main__':
    unittest.main()
