"""Exercise NVIDIA preflight diagnostics without drivers, GPUs, or pip changes."""

import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1] / 'roles/ct_runtime_vllm'


class NvidiaSmiPreflightTests(unittest.TestCase):
    def run_probe(self, stdout='', stderr='', rc=0, missing=False, overrides=None):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        with tempfile.TemporaryDirectory(prefix='ct-smi-preflight-') as directory:
            root = Path(directory)
            binary = root / 'nvidia-smi'
            if not missing:
                binary.write_text(
                    f'#!{os.sys.executable}\nimport sys\n'
                    f'print({stdout!r}, end="")\n'
                    f'print({stderr!r}, end="", file=sys.stderr)\nsys.exit({rc})\n')
                binary.chmod(0o755)
            tasks = copy.deepcopy(yaml.safe_load((ROLE / 'tasks/nvidia_smi_preflight.yml').read_text()))
            # Use the real shell PATH lookup; never discover a worker's own GPU tools.
            tasks[0]['environment'] = {'PATH': str(root)}
            values = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
            values.update(ansible_python_interpreter=os.sys.executable,
                          ct_runtime_vllm_fail_on_nvidia_smi_probe=True)
            values.update(overrides or {})
            tasks.append({'ansible.builtin.debug': {'msg': 'MODEL_INSTALL_FOLLOW_UP'}})
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump([{
                'hosts': 'localhost', 'gather_facts': False, 'vars': values, 'tasks': tasks,
            }], sort_keys=False))
            result = subprocess.run(
                [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                env=dict(os.environ, ANSIBLE_NOCOLOR='1',
                         ANSIBLE_HOME=str(root / 'ansible-home'),
                         ANSIBLE_LOCAL_TEMP=str(root / 'tmp')),
                text=True, capture_output=True, timeout=60,
            )
            return result.returncode, result.stdout + result.stderr

    def test_missing_executable_reports_the_command_error_before_follow_up(self):
        status, output = self.run_probe(missing=True)
        self.assertEqual(status, 2, output)
        self.assertIn('not found in CT PATH', output)
        self.assertIn('command error=', output)
        self.assertIn('does not provide nvidia-smi', output)
        self.assertNotIn('MODEL_INSTALL_FOLLOW_UP', output)

    def test_nvml_error_on_stdout_is_reported(self):
        message = 'Failed to initialize NVML: Driver/library version mismatch'
        status, output = self.run_probe(stdout=message, rc=18)
        self.assertEqual(status, 2, output)
        self.assertIn(message, output)
        self.assertNotIn('MODEL_INSTALL_FOLLOW_UP', output)

    def test_dynamic_loader_error_on_stderr_is_reported(self):
        message = 'error while loading shared libraries: libnvidia-ml.so.1'
        status, output = self.run_probe(stderr=message, rc=127)
        self.assertEqual(status, 2, output)
        self.assertIn(message, output)
        self.assertNotIn('MODEL_INSTALL_FOLLOW_UP', output)

    def test_gpu_inventory_allows_follow_up(self):
        status, output = self.run_probe(stdout='GPU 0: test GPU (UUID: fixture)\n')
        self.assertEqual(status, 0, output)
        self.assertIn('MODEL_INSTALL_FOLLOW_UP', output)

    def test_empty_success_is_rejected_or_warned_according_to_policy(self):
        for strict in [True, False]:
            with self.subTest(strict=strict):
                status, output = self.run_probe(overrides={'ct_runtime_vllm_fail_on_nvidia_smi_probe': strict})
                self.assertEqual(status, 2 if strict else 0, output)
                self.assertEqual('MODEL_INSTALL_FOLLOW_UP' in output, not strict)
                if not strict:
                    self.assertIn('nvidia-smi -L preflight failed in CT', output)

    def test_disabled_probe_and_non_cuda_runtime_skip_the_missing_binary(self):
        for overrides in [{'ct_runtime_vllm_require_nvidia_smi': False}, {'ct_runtime_vllm_device': 'cpu'}]:
            with self.subTest(overrides=overrides):
                status, output = self.run_probe(missing=True, overrides=overrides)
                self.assertEqual(status, 0, output)
                self.assertIn('MODEL_INSTALL_FOLLOW_UP', output)


if __name__ == '__main__':
    unittest.main()
