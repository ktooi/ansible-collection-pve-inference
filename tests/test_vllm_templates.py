"""Run with python -m unittest discover -s tests -p 'test_*.py'. No GPU required."""
from pathlib import Path
import unittest

import jinja2
from jinja2.nativetypes import NativeEnvironment
import yaml

ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'ct_runtime_vllm'


class VllmServiceTests(unittest.TestCase):
    def render(self, backend, logging):
        values = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        values.update(ct_runtime_vllm_backend=backend,
                      ct_runtime_vllm_systemd_log_to_files=logging,
                      ct_runtime_vllm_extra_args='--enforce-eager')
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
