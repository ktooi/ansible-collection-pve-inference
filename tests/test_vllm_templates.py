"""Run with python -m unittest discover -s tests -p 'test_*.py'. No GPU required."""
from pathlib import Path
import json
import shlex
import subprocess
import sys
import tempfile
import unittest

import jinja2
from jinja2.nativetypes import NativeEnvironment
import yaml

ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'ct_runtime_vllm'


class VllmServiceTests(unittest.TestCase):
    def render(self, backend, logging, **overrides):
        values = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        values.update(ct_runtime_vllm_backend=backend,
                      ct_runtime_vllm_systemd_log_to_files=logging,
                      ct_runtime_vllm_extra_args='--enforce-eager')
        values.update(overrides)
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROLE / 'templates'),
                                 undefined=jinja2.StrictUndefined)
        return env.get_template('vllm.service.j2').render(values)

    def test_core_keeps_existing_launch_options(self):
        for logging in [True, False]:
            with self.subTest(logging=logging):
                unit = self.render('core', logging)
                self.assertIn('--tensor-parallel-size', unit)
                self.assertIn('--max-model-len', unit)
                self.assertNotIn('--omni', unit)
                self.assertIn('${INFER_VLLM_EXTRA_ARGS}', unit)
                self.assertEqual(unit.count('ExecStart='), 1)

    def test_mtp_and_language_model_flags_reach_only_the_core_process(self):
        for backend in ['core', 'omni']:
            for logging in [True, False]:
                with self.subTest(backend=backend, logging=logging), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / 'bin').mkdir()
                    executable = root / 'bin/vllm'
                    executable.write_text(
                        f'#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
                    executable.chmod(0o755)
                    unit = self.render(
                        backend, logging, ct_runtime_vllm_venv=str(root),
                        ct_runtime_vllm_stdout_log=str(root / 'stdout.log'),
                        ct_runtime_vllm_stderr_log=str(root / 'stderr.log'),
                        ct_runtime_vllm_enable_mtp=True,
                        ct_runtime_vllm_speculative_method='qwen3_next_mtp',
                        ct_runtime_vllm_mtp_num_speculative_tokens=2,
                        ct_runtime_vllm_language_model_only=True)
                    command = next(line.removeprefix('ExecStart=') for line in unit.splitlines()
                                   if line.startswith('ExecStart='))
                    result = subprocess.run(
                        shlex.split(command), capture_output=True, text=True, timeout=15,
                        env={'PATH': '/usr/bin:/bin', 'INFER_VLLM_MODEL': 'test/model',
                             'INFER_VLLM_BIND_HOST': '127.0.0.1', 'INFER_VLLM_PORT': '8000',
                             'INFER_VLLM_EXTRA_ARGS': '--enforce-eager'})
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    arguments = json.loads(result.stdout)
                    if backend == 'core':
                        self.assertIn('--language-model-only', arguments)
                        speculative = json.loads(arguments[arguments.index('--speculative_config') + 1])
                        self.assertEqual(speculative, {'method': 'qwen3_next_mtp', 'num_speculative_tokens': 2})
                    else:
                        self.assertIn('--omni', arguments)
                        self.assertNotIn('--language-model-only', arguments)
                        self.assertNotIn('--speculative_config', arguments)

    def test_omni_omits_language_model_options(self):
        for logging in [True, False]:
            with self.subTest(logging=logging):
                unit = self.render('omni', logging)
                self.assertIn('--omni', unit)
                self.assertIn('--port ${INFER_VLLM_PORT}', unit)
                for option in ['--tensor-parallel-size', '--max-model-len',
                               '--kv-cache-dtype', '--gpu-memory-utilization']:
                    self.assertNotIn(option, unit)
                self.assertIn('${INFER_VLLM_EXTRA_ARGS}', unit)
                self.assertEqual(unit.count('ExecStart='), 1)


class VllmPackageTests(unittest.TestCase):
    def test_modality_packages_are_resolved_together(self):
        tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        install = next(task['ansible.builtin.pip'] for task in tasks
                       if task['name'] == 'Install vLLM and optional modality dependencies together')
        env = NativeEnvironment(undefined=jinja2.StrictUndefined)
        for backend in ['core', 'omni']:
            for pinned in [False, True]:
                with self.subTest(backend=backend, pinned=pinned):
                    values = dict(ct_runtime_vllm_audio=True,
                                  ct_runtime_vllm_backend=backend,
                                  ct_runtime_vllm_version='0.32.0' if pinned else '',
                                  ct_runtime_vllm_omni_version='0.32.0' if pinned else '',
                                  ct_runtime_vllm_additional_packages=['soundfile'])
                    packages = env.from_string(install['name']).render(values)
                    suffix = '==0.32.0' if pinned else ''
                    expected = ['vllm[audio]' + suffix]
                    if backend == 'omni':
                        expected.append('vllm-omni' + suffix)
                    self.assertEqual(packages, expected + ['soundfile'])


if __name__ == '__main__':
    unittest.main()
