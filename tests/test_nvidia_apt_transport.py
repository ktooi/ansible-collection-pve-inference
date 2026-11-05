"""Exercise the real file modules with a temporary APT configuration directory."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'host_nvidia_gpu'


class AptTransportTests(unittest.TestCase):
    def test_ipv4_override_can_be_enabled_and_removed_idempotently(self):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        with tempfile.TemporaryDirectory(prefix='nvidia-apt-transport-') as directory:
            root = Path(directory)
            config = root / '99-pve-inference-ipv4'
            # Keep all conditionals and file-module behavior. Only ownership is
            # adapted so the fixture can run without root; the path is a variable.
            tasks = yaml.safe_load((ROLE / 'tasks' / 'apt_transport.yml').read_text())
            tasks[0]['ansible.builtin.copy']['owner'] = str(os.getuid())
            tasks[0]['ansible.builtin.copy']['group'] = str(os.getgid())
            helper = root / 'apt_transport.yml'
            helper.write_text(yaml.safe_dump(tasks, sort_keys=False))
            env = dict(os.environ, ANSIBLE_NOCOLOR='1',
                       ANSIBLE_HOME=str(root / 'ansible-home'),
                       ANSIBLE_LOCAL_TEMP=str(root / 'tmp'))

            def run(enabled, expected_changes):
                playbook = root / 'test.yml'
                playbook.write_text(yaml.safe_dump([{
                    'hosts': 'localhost',
                    'gather_facts': False,
                    'vars': {
                        'ansible_python_interpreter': os.sys.executable,
                        'host_nvidia_gpu_apt_force_ipv4': enabled,
                        'host_nvidia_gpu_apt_force_ipv4_config_path': str(config),
                    },
                    'tasks': [{'ansible.builtin.import_tasks': str(helper)}],
                }], sort_keys=False))
                result = subprocess.run(
                    [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                    env=env, text=True, capture_output=True, timeout=60,
                )
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 0, output)
                match = re.search(r'changed=(\d+)', output)
                self.assertIsNotNone(match, output)
                self.assertEqual(int(match.group(1)), expected_changes, output)

            # Disabled by default: do not create a file or alter other overrides.
            other = root / 'site-apt.conf'
            other.write_text('Acquire::Retries "3";\n')
            run(False, 0)
            self.assertFalse(config.exists())
            run(True, 1)
            self.assertEqual(config.read_text(), 'Acquire::ForceIPv4 "true";\n')
            self.assertEqual(config.stat().st_mode & 0o777, 0o644)

            # Verify that APT itself accepts the generated directive, without
            # loading system configuration or contacting a repository.
            apt_config = shutil.which('apt-config')
            if apt_config:
                isolated = root / 'apt.conf'
                isolated.write_text('Dir::Etc::parts "-";\nDir::Etc::main "-";\n'
                                    f'#include "{config}";\n')
                result = subprocess.run(
                    [apt_config, 'shell', 'PVE_TEST_IPV4', 'Acquire::ForceIPv4'],
                    env=dict(os.environ, APT_CONFIG=str(isolated)),
                    text=True, capture_output=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("PVE_TEST_IPV4='true'", result.stdout)

            run(True, 0)
            run(False, 1)
            run(False, 0)
            self.assertFalse(config.exists())
            self.assertEqual(other.read_text(), 'Acquire::Retries "3";\n')


if __name__ == '__main__':
    unittest.main()
