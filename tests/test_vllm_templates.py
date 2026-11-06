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

    def test_lora_module_arguments_reach_core_only_in_both_logging_modes(self):
        for backend in ['core', 'omni']:
            for logging in [True, False]:
                with self.subTest(backend=backend, logging=logging), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / 'bin').mkdir()
                    binary = root / 'bin/vllm'
                    binary.write_text(f'#!{sys.executable}\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
                    binary.chmod(0o755)
                    adapters = [{'name': 'adapter-01', 'path': '/opt/inference/loras/adapter-01'},
                                {'name': 'adapter-02', 'path': '/opt/inference/loras/adapter-02'}]
                    unit = self.render(backend, logging, ct_runtime_vllm_venv=str(root),
                        ct_runtime_vllm_lora_adapters_normalized=adapters,
                        ct_runtime_vllm_max_lora_rank=64,
                        ct_runtime_vllm_stdout_log=str(root / 'stdout.log'),
                        ct_runtime_vllm_stderr_log=str(root / 'stderr.log'))
                    invocation = next(line.removeprefix('ExecStart=') for line in unit.splitlines() if line.startswith('ExecStart='))
                    result = subprocess.run(shlex.split(invocation), capture_output=True, text=True, timeout=15,
                        env={'PATH': '/usr/bin:/bin', 'INFER_VLLM_MODEL': 'fixture/base-model',
                             'INFER_VLLM_BIND_HOST': '127.0.0.1', 'INFER_VLLM_PORT': '8000',
                             'INFER_VLLM_EXTRA_ARGS': '--enforce-eager'})
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    arguments = json.loads(result.stdout)
                    if backend == 'core':
                        self.assertIn('--enable-lora', arguments)
                        self.assertEqual(arguments[arguments.index('--max-lora-rank') + 1], '64')
                        offset = arguments.index('--lora-modules')
                        self.assertEqual(arguments[offset + 1:offset + 3], [item['name'] + '=' + item['path'] for item in adapters])
                        self.assertEqual(arguments[offset + 3], '--enforce-eager')
                    else:
                        self.assertNotIn('--enable-lora', arguments)
                        self.assertNotIn('--lora-modules', arguments)
                        self.assertNotIn('--max-lora-rank', arguments)

    def test_resolved_nvcc_path_survives_login_profile_and_keeps_system_commands(self):
        for logging in [True, False]:
            with self.subTest(logging=logging), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'bin').mkdir()
                nvcc = root / 'bin/nvcc'
                nvcc.write_text('#!/bin/sh\nprintf "fixture nvcc\\n"\n')
                nvcc.chmod(0o755)
                executable = root / 'bin/vllm'
                executable.write_text(
                    f'#!{sys.executable}\nimport json, subprocess\n'
                    'print(json.dumps({"id": subprocess.check_output(["id", "-u"], text=True).strip(),\n'
                    '                  "nvcc": subprocess.check_output(["nvcc"], text=True).strip()}))\n')
                executable.chmod(0o755)
                overrides = dict(
                    ct_runtime_vllm_venv=str(root),
                    ct_runtime_vllm_cuda_home_effective=str(root),
                    ct_runtime_vllm_nvcc_bin_path_effective=str(root / 'bin'),
                    ct_runtime_vllm_stdout_log=str(root / 'stdout.log'),
                    ct_runtime_vllm_stderr_log=str(root / 'stderr.log'))
                values = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
                values.update(overrides)
                env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROLE / 'templates'),
                                         undefined=jinja2.StrictUndefined, trim_blocks=True)
                rendered = env.get_template('vllm.env.j2').render(values)
                environment = dict(line.split('=', 1) for line in rendered.splitlines() if '=' in line)
                self.assertNotIn('${PATH}', environment['PATH'])
                unit = self.render('omni', logging, **overrides)
                command = next(line.removeprefix('ExecStart=') for line in unit.splitlines()
                               if line.startswith('ExecStart='))
                # systemd turns $$ into a literal $ before invoking bash.
                command = command.replace('$$', '$')
                result = subprocess.run(shlex.split(command), env=environment,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn('command not found', result.stderr)
                output = json.loads(result.stdout)
                self.assertTrue(output['id'].isdigit())
                self.assertEqual(output['nvcc'], 'fixture nvcc')


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
