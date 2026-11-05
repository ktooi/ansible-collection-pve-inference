"""Exercise the NVIDIA helper contract without a GPU or mknod privileges."""

import copy
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

import jinja2
import yaml


ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'host_nvidia_gpu'
HELPER = '''
import os
from pathlib import Path
import sys
root = Path(os.environ['NVIDIA_TEST_STATE_DIR'])
uvm = '-u' in sys.argv
if not uvm and os.environ.get('NVIDIA_TEST_FAIL_CORE') == '1':
    print('fixture core node creation failed', file=sys.stderr)
    sys.exit(17)
for argument in sys.argv[1:]:
    if not argument.startswith('-c='):
        continue
    minor = int(argument.partition('=')[2])
    if uvm and minor == 0:
        (root / 'uvm').touch()
    elif not uvm and minor == 0:
        (root / 'gpu0').touch()
    elif not uvm and minor == 255:
        (root / 'control').touch()
'''


class DeviceNodeTests(unittest.TestCase):
    def create_helper(self, root):
        helper = root / 'nvidia-modprobe'
        helper.write_text(f'#!{os.sys.executable}\n' + HELPER)
        helper.chmod(0o755)
        return helper

    def run_tasks(self, root, helper, fail_core=False):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        tasks = yaml.safe_load((ROLE / 'tasks' / 'device_nodes.yml').read_text())
        for command in tasks[0]['loop']:
            command[0] = str(helper)
        if fail_core:
            # Keep the real node assertion and diagnostic templates, with stat
            # observations supplied at the device-I/O boundary.
            tasks.append({'ansible.builtin.set_fact': {'host_nvidia_critical_nodes': {'results': [
                {'item': '/dev/nvidiactl', 'stat': {'exists': False}},
                {'item': '/dev/nvidia-uvm', 'stat': {'exists': True, 'ischr': True}},
            ]}}})
            source = yaml.safe_load((ROLE / 'tasks' / 'main.yml').read_text())
            tasks.append(copy.deepcopy(next(t for t in source if t.get('name') ==
                                           'Assert critical host NVIDIA nodes are character devices')))
        playbook = root / 'test.yml'
        playbook.write_text(yaml.safe_dump([{
            'hosts': 'localhost', 'gather_facts': False,
            'vars': {'ansible_python_interpreter': os.sys.executable,
                     'host_nvidia_gpu_require_nvidia_devices': True},
            'environment': {'NVIDIA_TEST_STATE_DIR': str(root),
                            'NVIDIA_TEST_FAIL_CORE': '1' if fail_core else '0'},
            'tasks': tasks,
        }], sort_keys=False))
        env = dict(os.environ, ANSIBLE_NOCOLOR='1',
                   ANSIBLE_HOME=str(root / 'ansible-home'),
                   ANSIBLE_LOCAL_TEMP=str(root / 'tmp'))
        result = subprocess.run([executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                                env=env, text=True, capture_output=True, timeout=60)
        return result.returncode, result.stdout + result.stderr

    def test_role_requests_gpu_control_and_uvm_nodes(self):
        with tempfile.TemporaryDirectory(prefix='nvidia-node-test-') as directory:
            root = Path(directory)
            status, output = self.run_tasks(root, self.create_helper(root))
            self.assertEqual(status, 0, output)
            for node in ['gpu0', 'control', 'uvm']:
                self.assertTrue((root / node).is_file(), node)

    def test_failure_reports_missing_node_and_original_helper_error(self):
        with tempfile.TemporaryDirectory(prefix='nvidia-node-error-') as directory:
            root = Path(directory)
            status, output = self.run_tasks(root, self.create_helper(root), fail_core=True)
            self.assertEqual(status, 2, output)
            self.assertIn('/dev/nvidiactl: exists=False', output)
            self.assertIn('rc=17', output)
            self.assertIn('fixture core node creation failed', output)
            self.assertTrue((root / 'uvm').is_file())

    def test_boot_service_requests_both_families_before_waiting(self):
        values = yaml.safe_load((ROLE / 'defaults' / 'main.yml').read_text())
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROLE / 'templates'),
                                 undefined=jinja2.StrictUndefined)
        unit = env.get_template('nvidia-uvm-devices.service.j2').render(values)
        commands = [line.partition('=')[2] for line in unit.splitlines() if line.startswith('ExecStart=')]
        self.assertEqual(len(commands), 3)
        self.assertIn('Before=pve-guests.service', unit)
        self.assertIn('[ -c /dev/nvidiactl ] && [ -c /dev/nvidia-uvm ]', commands[2])
        with tempfile.TemporaryDirectory(prefix='nvidia-node-unit-') as directory:
            root = Path(directory)
            helper = self.create_helper(root)
            for command in commands[:2]:
                argv = shlex.split(command)
                self.assertEqual(argv[0], '/usr/bin/nvidia-modprobe')
                subprocess.run([str(helper), *argv[1:]], check=True,
                               env=dict(os.environ, NVIDIA_TEST_STATE_DIR=str(root),
                                        NVIDIA_TEST_FAIL_CORE='0'))
            for node in ['gpu0', 'control', 'uvm']:
                self.assertTrue((root / node).is_file(), node)


if __name__ == '__main__':
    unittest.main()
