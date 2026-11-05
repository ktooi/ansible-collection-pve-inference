"""Exercise Ansible failure handling with APT operations replaced by local fixtures.

Run: python -m unittest discover -s tests -p 'test_*.py' -v
Requires ansible-core and PyYAML. No root access or package changes are needed.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'nvidia_cuda_repo_common'
FIXTURE_MODULE = '''
from ansible.module_utils.basic import AnsibleModule
import os

module = AnsibleModule(argument_spec={
    'name': {'type': 'raw'}, 'state': {'type': 'str'},
    'update_cache': {'type': 'bool'}, 'deb': {'type': 'str'},
    'repo': {'type': 'str'}, 'filename': {'type': 'str'},
}, supports_check_mode=True)
error = os.environ.get('NVIDIA_APT_FIXTURE_ERROR', '')
if error and module.params['name']:
    module.fail_json(msg=error)
module.exit_json(changed=False)
'''


def replace_package_operations(tasks):
    """Stub only package I/O; retain the role's block/rescue and templates."""
    for task in tasks:
        for key in ('ansible.builtin.apt', 'ansible.builtin.apt_repository'):
            if key in task:
                task['ansible.legacy.fixture_apt'] = task.pop(key)
        for key in ('block', 'rescue', 'always'):
            replace_package_operations(task.get(key, []))


class AptBootstrapTests(unittest.TestCase):
    def run_role(self, error=''):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        with tempfile.TemporaryDirectory(prefix='nvidia-apt-test-') as directory:
            root = Path(directory)
            role = root / 'roles' / 'cuda_repo'
            shutil.copytree(ROLE, role)
            task_file = role / 'tasks' / 'main.yml'
            tasks = yaml.safe_load(task_file.read_text())
            replace_package_operations(tasks)
            task_file.write_text(yaml.safe_dump(tasks, sort_keys=False))
            (root / 'library').mkdir()
            (root / 'library' / 'fixture_apt.py').write_text(FIXTURE_MODULE)
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump([{
                'name': 'Exercise CUDA repository bootstrap',
                'hosts': 'localhost',
                'gather_facts': False,
                'vars': {'ansible_python_interpreter': os.sys.executable},
                'environment': {'NVIDIA_APT_FIXTURE_ERROR': error},
                'roles': ['cuda_repo'],
            }], sort_keys=False))
            env = dict(os.environ, ANSIBLE_NOCOLOR='1',
                       ANSIBLE_HOME=str(root / 'ansible-home'),
                       ANSIBLE_LOCAL_TEMP=str(root / 'tmp'),
                       ANSIBLE_LIBRARY=str(root / 'library'),
                       ANSIBLE_ROLES_PATH=str(root / 'roles'))
            return subprocess.run(
                [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                env=env, capture_output=True, text=True, timeout=60,
            )

    def test_nosplit_preserves_original_error_and_stops_before_cuda_changes(self):
        error = "repo.zabbix.com bookworm InRelease: Clearsigned file isn't valid, got 'NOSPLIT'"
        result = self.run_role(error)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, output)
        self.assertIn(error, output)
        self.assertIn('ALL enabled APT sources', output)
        self.assertIn('trixie', output)
        self.assertIn('Do not disable signature verification', output)
        self.assertNotIn('TASK [cuda_repo : Install NVIDIA CUDA keyring package]', output)
        self.assertNotIn('TASK [cuda_repo : Configure NVIDIA CUDA apt repository]', output)

    def test_other_apt_errors_are_not_hidden(self):
        result = self.run_role('Could not get lock /var/lib/dpkg/lock-frontend')
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2, output)
        self.assertIn('Could not get lock /var/lib/dpkg/lock-frontend', output)
        self.assertNotIn('TASK [cuda_repo : Install NVIDIA CUDA keyring package]', output)

    def test_success_continues_to_cuda_repository_configuration(self):
        result = self.run_role()
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn('TASK [cuda_repo : Install NVIDIA CUDA keyring package]', output)
        self.assertIn('TASK [cuda_repo : Configure NVIDIA CUDA apt repository]', output)
        self.assertNotIn('APT prerequisite installation failed', output)


if __name__ == '__main__':
    unittest.main()
