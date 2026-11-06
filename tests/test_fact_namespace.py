"""Verify distro selection and host checks with injected fact variables disabled."""

import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
CT_ROLES = ['ct_runtime_common', 'ct_runtime_launcher_common', 'ct_runtime_vllm',
            'ct_runtime_tgi', 'ct_runtime_sglang', 'ct_runtime_ollama', 'ct_validate']


class FactNamespaceTests(unittest.TestCase):
    def run_plays(self, plays):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        with tempfile.TemporaryDirectory(prefix='fact-namespace-') as directory:
            root = Path(directory)
            collection = root / 'collections/ansible_collections/ktooi/pve_inference'
            collection.parent.mkdir(parents=True)
            collection.symlink_to(ROOT, target_is_directory=True)
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump(plays, sort_keys=False))
            result = subprocess.run(
                [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                env=dict(os.environ, ANSIBLE_NOCOLOR='1', ANSIBLE_INJECT_FACT_VARS='False',
                         ANSIBLE_HOME=str(root / 'ansible-home'),
                         ANSIBLE_LOCAL_TEMP=str(root / 'tmp'),
                         ANSIBLE_COLLECTIONS_PATH=str(root / 'collections')),
                text=True, capture_output=True, timeout=60,
            )
            return result.returncode, result.stdout + result.stderr

    def test_all_ct_roles_load_distro_vars_without_injected_aliases(self):
        plays = []
        for distribution, major in [('Debian', '13'), ('Ubuntu', '24'), ('Rocky', '9')]:
            tasks = [{'ansible.builtin.assert': {'that': [
                'ansible_distribution is not defined', 'ansible_distribution_major_version is not defined',
            ]}}]
            for role in CT_ROLES:
                tasks += [
                    {'ansible.builtin.include_role': {
                        'name': 'ktooi.pve_inference.' + role, 'tasks_from': 'variables.yml',
                    }},
                    {'ansible.builtin.assert': {'that': [f"{role}_distribution_key == '{distribution.lower()}'"]}},
                ]
            plays.append({'hosts': 'localhost', 'gather_facts': False,
                          'vars': {'ansible_facts': {'distribution': distribution, 'distribution_major_version': major}},
                          'tasks': tasks})
        status, output = self.run_plays(plays)
        self.assertEqual(status, 0, output)
        self.assertNotIn('INJECT_FACTS_AS_VARS', output)

    def test_nvidia_host_checks_and_header_defaults_use_the_facts_namespace(self):
        role = ROOT / 'roles/host_nvidia_gpu'
        defaults = yaml.safe_load((role / 'defaults/main.yml').read_text())
        source = yaml.safe_load((role / 'tasks/main.yml').read_text())
        tasks = copy.deepcopy(source[:2])
        tasks.append({'ansible.builtin.assert': {'that': [
            "host_nvidia_gpu_header_packages == ['pve-headers-7.0.14-28-pve']",
            'ansible_kernel is not defined', 'ansible_os_family is not defined',
        ]}})
        status, output = self.run_plays([{
            'hosts': 'localhost', 'gather_facts': False,
            'vars': {**defaults, 'ansible_facts': {'os_family': 'Debian', 'kernel': '7.0.14-28-pve'}},
            'tasks': tasks,
        }])
        self.assertEqual(status, 0, output)
        self.assertNotIn('INJECT_FACTS_AS_VARS', output)


if __name__ == '__main__':
    unittest.main()
