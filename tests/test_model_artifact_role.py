"""Run the real Ansible download role against a small local HTTP fixture."""

import functools
import grp
import hashlib
import http.server
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tempfile
import threading
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class ModelArtifactRoleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='model-artifact-role-')
        self.root = Path(self.temporary.name)
        self.web = self.root / 'web'
        self.web.mkdir()
        self.requests = []
        requests = self.requests

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                requests.append(self.path)
                super().do_GET()

        self.server = http.server.ThreadingHTTPServer(
            ('127.0.0.1', 0), functools.partial(Handler, directory=str(self.web)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        collection = self.root / 'collections/ansible_collections/ktooi/pve_inference'
        collection.parent.mkdir(parents=True)
        collection.symlink_to(ROOT, target_is_directory=True)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def run_role(self, assets, *, check=False, lora=None, backend='omni', maximum=16, integration=False, private_logs=False, overrides=None):
        values = {
            'ansible_python_interpreter': os.sys.executable,
            'ct_model_artifacts': assets,
            'ct_model_artifacts_owner': pwd.getpwuid(os.getuid()).pw_name,
            'ct_model_artifacts_group': grp.getgrgid(os.getgid()).gr_name,
            'ct_model_artifacts_no_log': private_logs,
        }
        values.update(overrides or {})
        if integration:
            source = yaml.safe_load((ROOT / 'roles/ct_runtime_vllm/tasks/main.yml').read_text())
            tasks = [next(task for task in source if task['name'] == 'Deploy managed model and LoRA artifacts')]
            values.update(ct_runtime_vllm_user=values['ct_model_artifacts_owner'],
                          ct_runtime_vllm_group=values['ct_model_artifacts_group'])
        else:
            tasks = [{'ansible.builtin.include_role': {'name': 'ktooi.pve_inference.ct_model_artifacts'}}]
        if lora is not None:
            values.update(ct_runtime_vllm_lora_adapters=lora,
                          ct_runtime_vllm_backend=backend,
                          ct_runtime_vllm_max_lora_rank=maximum)
            tasks += [
                {'ansible.builtin.include_role': {'name': 'ktooi.pve_inference.ct_runtime_vllm', 'tasks_from': 'lora_settings.yml'}},
                {'ansible.builtin.include_role': {'name': 'ktooi.pve_inference.ct_runtime_vllm', 'tasks_from': 'lora.yml'}},
                {'ansible.builtin.debug': {'var': 'ct_runtime_vllm_lora_requests'}},
            ]
        playbook = self.root / 'test.yml'
        playbook.write_text(yaml.safe_dump([{
            'hosts': 'localhost', 'gather_facts': False, 'vars': values, 'tasks': tasks,
            'handlers': [{'name': 'Restart vllm', 'ansible.builtin.debug': {'msg': 'Runtime restart notified'}}],
        }], sort_keys=False))
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        args = [executable, '-i', 'localhost,', '-c', 'local', str(playbook)]
        if check:
            args.append('--check')
        result = subprocess.run(args, capture_output=True, text=True, timeout=60,
            env=dict(os.environ, ANSIBLE_NOCOLOR='1', ANSIBLE_HOME=str(self.root / 'ansible-home'),
                     ANSIBLE_LOCAL_TEMP=str(self.root / 'tmp'),
                     ANSIBLE_COLLECTIONS_PATH=str(self.root / 'collections'),
                     NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost'))
        return result.returncode, result.stdout + result.stderr

    def asset(self, filename, data, *, dest=None):
        (self.web / filename).write_bytes(data)
        return {'name': filename, 'url': 'http://127.0.0.1:{}/{}'.format(self.server.server_port, filename),
                'dest': str(dest or self.root / 'deployed' / filename),
                'checksum': 'sha256:' + hashlib.sha256(data).hexdigest()}

    def test_download_is_idempotent_and_omni_request_metadata_is_usable(self):
        directory = self.root / 'adapter-01'
        assets = [
            self.asset('adapter_config.json', json.dumps({'peft_type': 'LORA', 'r': 16}).encode(), dest=directory / 'adapter_config.json'),
            self.asset('adapter_model.safetensors', b'fixture weights', dest=directory / 'adapter_model.safetensors'),
        ]
        adapter = [{'name': 'adapter-01', 'path': str(directory), 'scale': 0.8}]
        status, output = self.run_role(assets, lora=adapter)
        self.assertEqual(status, 0, output)
        self.assertIn('local_path', output)
        self.assertIn('0.8', output)
        self.assertEqual((directory / 'adapter_model.safetensors').read_bytes(), b'fixture weights')
        count = len(self.requests)
        status, output = self.run_role(assets, lora=adapter)
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertEqual(len(self.requests), count, output)

    def test_bad_download_hash_keeps_the_previous_file(self):
        asset = self.asset('weights', b'new verified weights')
        destination = Path(asset['dest'])
        destination.parent.mkdir()
        destination.write_bytes(b'previous weights')
        (self.web / 'weights').write_bytes(b'incorrect incoming bytes')
        status, output = self.run_role([asset])
        self.assertNotEqual(status, 0, output)
        self.assertIn('checksum', output.lower())
        self.assertEqual(destination.read_bytes(), b'previous weights')

    def test_check_mode_makes_no_requests_or_files(self):
        asset = self.asset('weights', b'weights')
        status, output = self.run_role([asset], check=True)
        self.assertEqual(status, 0, output)
        self.assertEqual(self.requests, [])
        self.assertFalse(Path(asset['dest']).exists())

    def test_default_private_logging_does_not_expose_source_query(self):
        asset = self.asset('weights', b'weights')
        asset['url'] += '?source_token=fixture-private-value'
        status, output = self.run_role([asset], private_logs=True)
        self.assertEqual(status, 0, output)
        self.assertNotIn('fixture-private-value', output)
        self.assertNotIn(asset['url'], output)

    def test_missing_adapter_layout_stops_before_runtime_configuration(self):
        status, output = self.run_role([], lora=[{'name': 'adapter-01', 'path': str(self.root / 'missing')}])
        self.assertNotEqual(status, 0, output)
        self.assertIn('Require complete local PEFT adapter directories', output)
        self.assertIn('Renaming an incompatible checkpoint', output)

    def test_vllm_integration_notifies_restart_only_for_changed_assets(self):
        asset = self.asset('weights', b'managed weights')
        status, output = self.run_role([asset], integration=True)
        self.assertEqual(status, 0, output)
        self.assertIn('Runtime restart notified', output)
        status, output = self.run_role([asset], integration=True)
        self.assertEqual(status, 0, output)
        self.assertNotIn('Runtime restart notified', output)

    def test_existing_directory_is_not_used_as_a_download_filename(self):
        destination = self.root / 'existing-directory'
        destination.mkdir()
        asset = self.asset('weights', b'weights', dest=destination)
        status, output = self.run_role([asset])
        self.assertNotEqual(status, 0, output)
        self.assertIn('Artifact destinations must be absent or regular files', output)
        self.assertEqual(self.requests, [])

    def test_user_download_preserves_preprovisioned_metadata_without_owner_lookup(self):
        directory = self.root / 'preprovisioned-models'
        directory.mkdir()
        directory.chmod(0o2770)
        destination = directory / 'weights'
        destination.write_bytes(b'old weights')
        destination.chmod(0o640)
        asset = self.asset('weights', b'verified shared weights', dest=destination)
        account = pwd.getpwuid(os.getuid()).pw_name
        overrides = {
            'ct_model_artifacts_become_user': account,
            'ct_model_artifacts_manage_permissions': False,
            'ct_model_artifacts_owner': 'nonexistent-model-owner-fixture',
            'ct_model_artifacts_group': 'nonexistent-model-group-fixture',
        }
        status, output = self.run_role([asset], overrides=overrides)
        self.assertEqual(status, 0, output)
        self.assertEqual(destination.read_bytes(), b'verified shared weights')
        self.assertEqual(destination.stat().st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o2770)
        count = len(self.requests)
        status, output = self.run_role([asset], overrides=overrides)
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertEqual(len(self.requests), count)

    def test_user_download_bad_checksum_preserves_previous_bytes_and_permissions(self):
        directory = self.root / 'preprovisioned-models'
        directory.mkdir(mode=0o750)
        destination = directory / 'weights'
        destination.write_bytes(b'previous shared weights')
        destination.chmod(0o640)
        asset = self.asset('weights', b'expected new weights', dest=destination)
        (self.web / 'weights').write_bytes(b'bad incoming bytes')
        status, output = self.run_role([asset], overrides={
            'ct_model_artifacts_become_user': pwd.getpwuid(os.getuid()).pw_name,
            'ct_model_artifacts_manage_permissions': False,
        })
        self.assertNotEqual(status, 0, output)
        self.assertIn('checksum', output.lower())
        self.assertEqual(destination.read_bytes(), b'previous shared weights')
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)
        self.assertEqual(sorted(path.name for path in directory.iterdir()), ['weights'])

    def test_invalid_permission_controls_fail_before_download(self):
        asset = self.asset('weights', b'weights')
        for overrides in [
            {'ct_model_artifacts_manage_permissions': 'false'},
            {'ct_model_artifacts_become_user': ['infer']},
        ]:
            with self.subTest(overrides=overrides):
                status, output = self.run_role([asset], overrides=overrides)
                self.assertNotEqual(status, 0, output)
                self.assertEqual(self.requests, [])
                self.assertFalse(Path(asset['dest']).parent.exists())

    def test_core_rank_above_limit_is_rejected_and_supported_rank_succeeds(self):
        directory = self.root / 'adapter-01'
        assets = [
            self.asset('adapter_config.json', json.dumps({'peft_type': 'LORA', 'r': 64}).encode(), dest=directory / 'adapter_config.json'),
            self.asset('adapter_model.safetensors', b'fixture weights', dest=directory / 'adapter_model.safetensors'),
        ]
        adapter = [{'name': 'adapter-01', 'path': str(directory)}]
        status, output = self.run_role(assets, lora=adapter, backend='core', maximum=16)
        self.assertNotEqual(status, 0, output)
        self.assertIn('Validate PEFT type and configured rank', output)
        status, output = self.run_role(assets, lora=adapter, backend='core', maximum=64)
        self.assertEqual(status, 0, output)


if __name__ == '__main__':
    unittest.main()
