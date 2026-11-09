"""Exercise the common role's native/Python paths without changing OS accounts."""

import grp
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles' / 'ct_runtime_common'


class RuntimeCommonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='runtime-common-')
        self.root = Path(self.temporary.name)
        collection = self.root / 'collections/ansible_collections/ktooi/pve_inference'
        fixture = collection / 'roles/ct_runtime_common'
        fixture.parent.mkdir(parents=True)
        shutil.copytree(ROLE, fixture)

        # Keep the real role's conditions, imports, variables and file operations.
        # Only package and account mutations are stubbed on the development host.
        tasks = yaml.safe_load((fixture / 'tasks/main.yml').read_text())

        def stub_mutations(entries):
            for task in entries:
                for key in ('block', 'rescue', 'always'):
                    if key in task:
                        stub_mutations(task[key])
                for module in ('apt', 'package', 'user', 'group'):
                    action = 'ansible.builtin.' + module
                    if action in task:
                        task.pop(action)
                        task['ansible.builtin.debug'] = {'msg': 'STUB_' + module.upper()}

        stub_mutations(tasks)
        (fixture / 'tasks/main.yml').write_text(yaml.safe_dump(tasks, sort_keys=False))
        self.log = self.root / 'venv-calls.jsonl'
        fakebin = self.root / 'fakebin'
        fakebin.mkdir()
        python = fakebin / 'python3'
        python.write_text(
            f'#!{os.sys.executable}\n'
            'import json, pathlib, sys\n'
            f'with pathlib.Path({str(self.log)!r}).open("a") as log:\n'
            '    log.write(json.dumps(sys.argv[1:]) + "\\n")\n'
            'assert sys.argv[1:3] == ["-m", "venv"]\n'
            'assert len(sys.argv) == 4\n'
            'destination = pathlib.Path(sys.argv[3]) / "bin"\n'
            'destination.mkdir(parents=True)\n'
            '(destination / "activate").write_text("fixture activation\\n")\n')
        python.chmod(0o755)
        self.venv = self.root / 'runtime with spaces' / 'venv'
        self.runtime_dir = self.root / 'runtime-data'
        self.env = dict(
            os.environ, ANSIBLE_NOCOLOR='1',
            ANSIBLE_COLLECTIONS_PATH=str(self.root / 'collections'),
            ANSIBLE_HOME=str(self.root / 'ansible-home'),
            ANSIBLE_LOCAL_TEMP=str(self.root / 'tmp'),
            PATH=str(fakebin) + os.pathsep + os.environ.get('PATH', ''))

    def tearDown(self):
        self.temporary.cleanup()

    def run_role(self, **overrides):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        values = {
            'ansible_python_interpreter': os.sys.executable,
            'ansible_facts': {'distribution': 'Ubuntu', 'distribution_major_version': '24',
                              'os_family': 'Debian'},
            'ct_runtime_common_user': pwd.getpwuid(os.getuid()).pw_name,
            'ct_runtime_common_group': grp.getgrgid(os.getgid()).gr_name,
            'ct_runtime_common_home': str(self.root / 'service-home'),
            'ct_runtime_common_venv': str(self.venv),
            'ct_runtime_common_directories': [str(self.runtime_dir)],
        }
        values.update(overrides)
        playbook = self.root / 'test.yml'
        playbook.write_text(yaml.safe_dump([{
            'hosts': 'localhost', 'gather_facts': False, 'vars': values,
            'roles': ['ktooi.pve_inference.ct_runtime_common'],
        }], sort_keys=False))
        result = subprocess.run(
            [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
            capture_output=True, text=True, timeout=60, env=self.env)
        return result.returncode, result.stdout + result.stderr

    def test_existing_default_creates_venv_and_second_run_is_idempotent(self):
        status, output = self.run_role()
        self.assertEqual(status, 0, output)
        self.assertTrue((self.venv / 'bin/activate').is_file())
        self.assertEqual(json.loads(self.log.read_text()), ['-m', 'venv', str(self.venv)])
        status, output = self.run_role()
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_native_runtime_skips_venv_but_keeps_common_preparation(self):
        status, output = self.run_role(ct_runtime_common_create_venv=False)
        self.assertEqual(status, 0, output)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.venv.exists())
        self.assertTrue(self.runtime_dir.is_dir())
        self.assertIn('STUB_USER', output)
        self.assertIn('STUB_GROUP', output)

    def test_string_boolean_is_rejected_before_mutations(self):
        status, output = self.run_role(ct_runtime_common_create_venv='false')
        self.assertNotEqual(status, 0, output)
        self.assertIn('must be a YAML boolean', output)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.runtime_dir.exists())
        self.assertNotIn('STUB_USER', output)
        self.assertNotIn('STUB_APT', output)


if __name__ == '__main__':
    unittest.main()
