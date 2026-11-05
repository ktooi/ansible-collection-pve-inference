"""Exercise vLLM package ordering and version-pin preflight without installing packages."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'ct_runtime_vllm'
PACKAGE_MODULE = '''
from ansible.module_utils.basic import AnsibleModule
import json
import os

module = AnsibleModule(argument_spec={
    'name': {'type': 'raw'}, 'state': {'type': 'str', 'default': 'present'},
    'virtualenv': {'type': 'str'}, 'extra_args': {'type': 'str'},
})
names = module.params['name']
with open(os.environ['VLLM_TEST_PACKAGE_LOG'], 'a') as stream:
    stream.write(json.dumps({
        'name': [names] if isinstance(names, str) else names,
        'state': module.params['state'],
    }) + '\\n')
module.exit_json(changed=True)
'''


class VllmInstallationTests(unittest.TestCase):
    def run_tasks(self, tasks, overrides):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        values = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        values.update(overrides)
        with tempfile.TemporaryDirectory(prefix='vllm-installation-') as directory:
            root = Path(directory)
            journal = root / 'packages.jsonl'
            library = root / 'library'
            library.mkdir()
            (library / 'fixture_vllm_pip.py').write_text(PACKAGE_MODULE)
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump([{
                'hosts': 'localhost', 'gather_facts': False,
                'vars': dict(values, ansible_python_interpreter=os.sys.executable),
                'environment': {'VLLM_TEST_PACKAGE_LOG': str(journal)},
                'tasks': tasks,
                'handlers': [{'name': 'Restart vllm', 'ansible.builtin.debug': {
                    'msg': 'Fixture restart notification received',
                }}],
            }], sort_keys=False))
            result = subprocess.run(
                [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                env=dict(os.environ, ANSIBLE_NOCOLOR='1',
                         ANSIBLE_HOME=str(root / 'ansible-home'),
                         ANSIBLE_LOCAL_TEMP=str(root / 'tmp'),
                         ANSIBLE_LIBRARY=str(library)),
                text=True, capture_output=True, timeout=60,
            )
            records = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
            return result.returncode, result.stdout + result.stderr, records

    def test_modality_dependencies_are_installed_once_before_torch_override(self):
        source = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        tasks = []
        for task in source:
            if 'ansible.builtin.pip' in task:
                task = copy.deepcopy(task)
                task['ansible.legacy.fixture_vllm_pip'] = task.pop('ansible.builtin.pip')
                tasks.append(task)
        status, output, records = self.run_tasks(tasks, {
            'ct_runtime_vllm_backend': 'omni',
            'ct_runtime_vllm_audio': True,
            'ct_runtime_vllm_version': '0.32.0',
            'ct_runtime_vllm_omni_version': '0.32.0',
            'ct_runtime_vllm_additional_packages': ['soundfile'],
            'ct_runtime_vllm_pip_state': 'latest',
            'ct_runtime_vllm_torch_package': 'torch==2.13.0',
            'ct_runtime_vllm_auto_install_nvcc_pip_fallback_effective': False,
        })
        self.assertEqual(status, 0, output)
        self.assertEqual(records, [
            {'name': ['vllm[audio]==0.32.0', 'vllm-omni==0.32.0', 'soundfile'], 'state': 'latest'},
            {'name': ['torch==2.13.0'], 'state': 'forcereinstall'},
        ])

    def test_version_pin_preflight_does_not_require_torch_backend_hint(self):
        source = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        names = {
            'Build effective torch CUDA probe mode for preflight',
            'Warn when strict probe is relaxed to count due to torch backend override',
        }
        tasks = [task for task in source if task.get('name') in names]
        tasks.append({'ansible.builtin.assert': {
            'that': ["ct_runtime_vllm_torch_cuda_probe_mode_effective == 'count'"],
        }})
        status, output, _ = self.run_tasks(tasks, {'ct_runtime_vllm_version': '0.32.0'})
        self.assertEqual(status, 0, output)
        self.assertIn('relaxed from strict to count', output)


if __name__ == '__main__':
    unittest.main()
