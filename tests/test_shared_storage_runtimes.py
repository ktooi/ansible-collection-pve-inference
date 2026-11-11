"""Exercise model-cache placement without a GPU or a network filesystem."""

import os
from pathlib import Path
import pwd
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]


class SharedModelCacheEnvironmentTests(unittest.TestCase):
    def environment(self, runtime, **overrides):
        role = ROOT / 'roles' / ('ct_runtime_' + runtime)
        values = yaml.safe_load((role / 'defaults/main.yml').read_text())
        values.update(overrides)
        environment = jinja2.Environment(
            loader=jinja2.FileSystemLoader(role / 'templates'),
            undefined=jinja2.StrictUndefined, trim_blocks=True)
        rendered = environment.get_template(runtime + '.env.j2').render(values)
        return {key: shlex.split(value)[0] if value else ''
                for key, value in (line.split('=', 1) for line in rendered.splitlines()
                                   if line.startswith(('HF_', 'HUGGINGFACE_')))}

    def test_default_configuration_does_not_relocate_hugging_face_data(self):
        for runtime in ['vllm', 'sglang', 'tgi']:
            with self.subTest(runtime=runtime):
                self.assertEqual(self.environment(runtime), {})

    def test_shared_hub_cache_keeps_home_and_token_paths_local(self):
        for runtime in ['vllm', 'sglang', 'tgi']:
            with self.subTest(runtime=runtime):
                configured = self.environment(runtime, **{
                    'ct_runtime_' + runtime + '_hf_hub_cache_dir': '/srv/models/hub',
                })
                self.assertEqual(configured, {
                    'HF_HUB_CACHE': '/srv/models/hub',
                    'HUGGINGFACE_HUB_CACHE': '/srv/models/hub',
                })
                self.assertNotIn('HF_HOME', configured)
                self.assertNotIn('HF_TOKEN_PATH', configured)

    def test_legacy_vllm_cache_setting_preserves_existing_behavior(self):
        self.assertEqual(self.environment(
            'vllm', ct_runtime_vllm_hf_cache_dir='/var/cache/legacy-hf'), {
                'HF_HOME': '/var/cache/legacy-hf',
                'HUGGINGFACE_HUB_CACHE': '/var/cache/legacy-hf',
            })


class SharedModelCacheValidationTests(unittest.TestCase):
    def test_vllm_rejects_mixed_home_and_hub_cache_settings(self):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        role = ROOT / 'roles/ct_runtime_vllm'
        source = yaml.safe_load((role / 'tasks/main.yml').read_text())
        validation = next(task for task in source
                          if task['name'] == 'Validate vLLM Hugging Face cache settings')
        values = yaml.safe_load((role / 'defaults/main.yml').read_text())
        values.update(ansible_python_interpreter=os.sys.executable,
                      ct_runtime_vllm_hf_cache_dir='/srv/shared-home',
                      ct_runtime_vllm_hf_hub_cache_dir='/srv/models/hub')
        with tempfile.TemporaryDirectory(prefix='cache-settings-') as directory:
            root = Path(directory)
            playbook = root / 'validate.yml'
            playbook.write_text(yaml.safe_dump([{
                'hosts': 'localhost', 'gather_facts': False,
                'vars': values, 'tasks': [validation],
            }], sort_keys=False))
            result = subprocess.run(
                [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
                capture_output=True, text=True, timeout=30,
                env=dict(os.environ, ANSIBLE_NOCOLOR='1',
                         ANSIBLE_HOME=str(root / 'ansible-home'),
                         ANSIBLE_LOCAL_TEMP=str(root / 'tmp')))
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Validate vLLM Hugging Face cache settings', result.stdout)
            self.assertIn('changed=0', result.stdout)


class PrecreatedOllamaDirectoryTests(unittest.TestCase):
    def run_directory_tasks(self, root, directory, manage=False):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        role = ROOT / 'roles/ct_runtime_ollama'
        source = yaml.safe_load((role / 'tasks/main.yml').read_text())
        names = {
            'Validate Ollama model directory management',
            'Ensure Ollama models directory exists',
            'Inspect the precreated Ollama model directory',
            'Require a readable precreated Ollama model directory',
        }
        tasks = [task for task in source if task['name'] in names]
        self.assertEqual(len(tasks), len(names))
        values = yaml.safe_load((role / 'defaults/main.yml').read_text())
        values.update(ansible_python_interpreter=os.sys.executable,
                      ct_runtime_ollama_manage_models_directory=manage,
                      ct_runtime_ollama_serve_models_path=str(directory),
                      ct_runtime_ollama_user=pwd.getpwuid(os.getuid()).pw_name,
                      ct_runtime_ollama_group='nonexistent-model-group-fixture')
        playbook = root / 'directory.yml'
        playbook.write_text(yaml.safe_dump([{
            'hosts': 'localhost', 'gather_facts': False,
            'vars': values, 'tasks': tasks,
        }], sort_keys=False))
        result = subprocess.run(
            [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
            capture_output=True, text=True, timeout=30,
            env=dict(os.environ, ANSIBLE_NOCOLOR='1',
                     ANSIBLE_HOME=str(root / 'ansible-home'),
                     ANSIBLE_LOCAL_TEMP=str(root / 'tmp')))
        return result.returncode, result.stdout + result.stderr

    def test_existing_directory_metadata_is_left_to_storage_administrator(self):
        with tempfile.TemporaryDirectory(prefix='ollama-models-') as name:
            root = Path(name)
            directory = root / 'models'
            directory.mkdir()
            directory.chmod(0o2770)
            status, output = self.run_directory_tasks(root, directory)
            self.assertEqual(status, 0, output)
            self.assertIn('changed=0', output)
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o2770)

    def test_missing_precreated_directory_fails_without_creating_a_local_fallback(self):
        with tempfile.TemporaryDirectory(prefix='ollama-models-') as name:
            root = Path(name)
            directory = root / 'missing-models'
            status, output = self.run_directory_tasks(root, directory)
            self.assertNotEqual(status, 0, output)
            self.assertIn('must exist and be readable/searchable', output)
            self.assertFalse(directory.exists())

    def test_string_management_flag_is_rejected_before_creating_directories(self):
        with tempfile.TemporaryDirectory(prefix='ollama-models-') as name:
            root = Path(name)
            directory = root / 'models'
            status, output = self.run_directory_tasks(root, directory, manage='false')
            self.assertNotEqual(status, 0, output)
            self.assertIn('must be a YAML boolean', output)
            self.assertFalse(directory.exists())


class RuntimeStorageBindingTests(unittest.TestCase):
    def test_extra_vars_cannot_retarget_another_services_guard(self):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        for runtime, label in [('vllm', 'vLLM'), ('sdcpp', 'sd.cpp'),
                               ('sglang', 'SGLang'), ('tgi', 'TGI'),
                               ('ollama', 'Ollama')]:
            with self.subTest(runtime=runtime), tempfile.TemporaryDirectory(
                    prefix='runtime-storage-binding-') as name:
                root = Path(name)
                role = ROOT / 'roles' / ('ct_runtime_' + runtime)
                tasks_file = 'models.yml' if runtime == 'sdcpp' else 'main.yml'
                source = yaml.safe_load((role / 'tasks' / tasks_file).read_text())
                binding = next(task for task in source
                               if task['name'] == 'Prepare optional shared model storage for ' + label)
                collection = root / 'collections/ansible_collections/ktooi/pve_inference'
                collection.parent.mkdir(parents=True)
                collection.symlink_to(ROOT, target_is_directory=True)
                other_guard = root / 'systemd/other.service.d/90-pve-inference-model-storage.conf'
                other_guard.parent.mkdir(parents=True)
                sentinel = '[Service]\nEnvironment=OTHER_RUNTIME=1\n'
                other_guard.write_text(sentinel)
                values = yaml.safe_load((role / 'defaults/main.yml').read_text())
                values.update(ansible_python_interpreter=os.sys.executable,
                              ct_model_storage_enabled=False,
                              ct_model_storage_helper_path=str(root / 'helper/check-storage'),
                              ct_model_storage_systemd_dir=str(root / 'systemd'))
                playbook = root / 'binding.yml'
                playbook.write_text(yaml.safe_dump([{
                    'hosts': 'localhost', 'gather_facts': False,
                    'vars': values, 'tasks': [binding],
                }], sort_keys=False))
                overrides = root / 'overrides.yml'
                overrides.write_text(yaml.safe_dump({
                    'ct_model_storage_service_name': 'other.service',
                }))
                command = [executable, '-i', 'localhost,', '-c', 'local', str(playbook)]
                environment = dict(os.environ, ANSIBLE_NOCOLOR='1',
                                   ANSIBLE_COLLECTIONS_PATH=str(root / 'collections'),
                                   ANSIBLE_HOME=str(root / 'ansible-home'),
                                   ANSIBLE_LOCAL_TEMP=str(root / 'tmp'))
                baseline = subprocess.run(command, capture_output=True, text=True,
                                          timeout=30, env=environment)
                self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
                self.assertIn('changed=0', baseline.stdout)
                self.assertEqual(other_guard.read_text(), sentinel)
                result = subprocess.run(command + ['-e', '@' + str(overrides)],
                                        capture_output=True, text=True, timeout=30,
                                        env=environment)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn('Reject shared-storage extra-vars that override the runtime binding', output)
                self.assertIn('changed=0', output)
                self.assertEqual(other_guard.read_text(), sentinel)
                self.assertFalse((root / 'helper').exists())


if __name__ == '__main__':
    unittest.main()
