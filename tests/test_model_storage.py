"""Exercise shared-storage checks without needing privileged NFS test mounts."""

import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles' / 'ct_model_storage'
SPEC = importlib.util.spec_from_file_location('model_storage_check', ROLE / 'files/model_storage_check.py')
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class StorageHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='model-storage-helper-')
        self.root = Path(self.temporary.name)
        self.mount = self.root / 'mount'
        self.namespace = self.mount / 'namespace'
        self.namespace.mkdir(parents=True)
        self.marker = self.namespace / 'model'
        self.marker.write_bytes(b'pre-existing model')

    def tearDown(self):
        self.temporary.cleanup()

    def filesystem(self, target=None, fstype='nfs4'):
        return {'target': str(target or self.mount), 'fstype': fstype}

    def check(self, access='write', entries=None):
        with mock.patch.object(HELPER, 'filesystem_for', side_effect=entries or [self.filesystem(), self.filesystem()]):
            return HELPER.check_storage(str(self.mount), str(self.namespace), ['nfs', 'nfs4'], access)

    def test_write_probe_preserves_existing_data_and_leaves_no_files(self):
        before = stat.S_IMODE(self.namespace.stat().st_mode)
        self.assertEqual(self.check(), 'nfs4')
        self.assertEqual(list(self.namespace.iterdir()), [self.marker])
        self.assertEqual(self.marker.read_bytes(), b'pre-existing model')
        self.assertEqual(stat.S_IMODE(self.namespace.stat().st_mode), before)

    def test_read_mode_never_creates_a_probe(self):
        with mock.patch.object(HELPER.tempfile, 'mkstemp', side_effect=AssertionError('read mode wrote a file')):
            self.assertEqual(self.check('read'), 'nfs4')

    def test_failed_rename_cleans_the_probe(self):
        with mock.patch.object(HELPER.os, 'rename', side_effect=OSError('rename denied')):
            with self.assertRaisesRegex(OSError, 'rename denied'):
                self.check()
        self.assertEqual(list(self.namespace.iterdir()), [self.marker])

    def test_unmounted_directory_and_local_bind_are_rejected_before_write(self):
        for entry, message in [(self.filesystem('/', 'ext4'), 'exact mountpoint'),
                               (self.filesystem(fstype='ext4'), 'disallowed filesystem')]:
            with self.subTest(entry=entry), mock.patch.object(HELPER, 'probe_access') as probe:
                with self.assertRaisesRegex(HELPER.StorageError, message):
                    self.check(entries=[entry])
                probe.assert_not_called()

    def test_nested_local_mount_is_rejected_even_beneath_valid_nfs(self):
        with mock.patch.object(HELPER, 'probe_access') as probe:
            with self.assertRaisesRegex(HELPER.StorageError, 'unexpected filesystem'):
                self.check(entries=[self.filesystem(), self.filesystem(self.namespace, 'tmpfs')])
            probe.assert_not_called()

    def test_missing_namespace_and_symlinked_namespace_are_not_created_or_followed(self):
        self.marker.unlink()
        self.namespace.rmdir()
        with self.assertRaisesRegex(HELPER.StorageError, 'already exist'):
            self.check()
        self.assertFalse(self.namespace.exists())
        self.namespace.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(HELPER.StorageError, 'Symlinks'):
            self.check()

    def test_path_validation_rejects_noncanonical_and_symlinked_ancestors(self):
        for path in ['/', '/tmp/a/../b', '/tmp/a/./b', '/tmp//a', '/tmp/a/', '/tmp/a b', '/tmp/a%u', 'relative']:
            with self.subTest(path=path), self.assertRaises(HELPER.StorageError):
                HELPER.validate_path(path)
        linked = self.root / 'linked'
        linked.symlink_to(self.namespace, target_is_directory=True)
        with self.assertRaisesRegex(HELPER.StorageError, 'Symlinks'):
            HELPER.validate_path(str(linked / 'not-yet-created'))

    def test_namespace_outside_mount_is_rejected(self):
        with self.assertRaisesRegex(HELPER.StorageError, 'beneath'):
            HELPER.check_storage(str(self.mount), str(self.root), ['nfs'], 'read')

    def test_findmnt_uses_explicit_json_columns_and_rejects_bad_output(self):
        response = subprocess.CompletedProcess([], 0, json.dumps({'filesystems': [self.filesystem()]}), '')
        with mock.patch.object(HELPER.subprocess, 'run', return_value=response) as run:
            self.assertEqual(HELPER.filesystem_for(str(self.mount)), self.filesystem())
            self.assertEqual(run.call_args.args[0], ['findmnt', '--json', '--first-only', '--target',
                                                    str(self.mount), '--output', 'TARGET,FSTYPE'])
        for output in ['not JSON', '{}', '{"filesystems": []}', '{"filesystems": [{"target": 3, "fstype": "nfs"}]}']:
            with self.subTest(output=output), mock.patch.object(HELPER.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 0, output, '')):
                with self.assertRaisesRegex(HELPER.StorageError, 'invalid filesystem'):
                    HELPER.filesystem_for(str(self.mount))

    @unittest.skipIf(os.getuid() == 0, 'Root bypasses the owner permission denial used by this fixture')
    def test_write_denial_is_checked_using_effective_identity(self):
        self.namespace.chmod(0o555)
        try:
            self.assertEqual(self.check('read'), 'nfs4')
            with self.assertRaises(PermissionError):
                self.check('write')
        finally:
            self.namespace.chmod(0o755)
        self.assertEqual(list(self.namespace.iterdir()), [self.marker])


class StorageRoleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='model-storage-role-')
        self.root = Path(self.temporary.name)
        self.mount = self.root / 'mount'
        self.namespace = self.mount / 'namespace'
        self.namespace.mkdir(parents=True)
        self.marker = self.namespace / 'model'
        self.marker.write_bytes(b'pre-existing model')
        self.helper = self.root / 'libexec/model-storage-check'
        self.systemd = self.root / 'systemd'
        self.dropin = self.systemd / 'fixture.service.d/90-pve-inference-model-storage.conf'
        self.state = self.root / 'findmnt-state.json'
        self.state.write_text(json.dumps({'mount': str(self.mount), 'fstype': 'nfs4'}))
        self.findmnt_calls = self.root / 'findmnt-calls.jsonl'
        fakebin = self.root / 'fakebin'
        fakebin.mkdir()
        findmnt = fakebin / 'findmnt'
        findmnt.write_text(
            f'#!{os.sys.executable}\n'
            'import json, pathlib, sys\n'
            f'state = json.loads(pathlib.Path({str(self.state)!r}).read_text())\n'
            f'with pathlib.Path({str(self.findmnt_calls)!r}).open("a") as log:\n'
            '    log.write(json.dumps(sys.argv[1:]) + "\\n")\n'
            'print(json.dumps({"filesystems": [{"target": state["mount"], "fstype": state["fstype"]}]}))\n')
        findmnt.chmod(0o755)
        collection = self.root / 'collections/ansible_collections/ktooi/pve_inference'
        fixture = collection / 'roles/ct_model_storage'
        fixture.parent.mkdir(parents=True)
        shutil.copytree(ROLE, fixture)
        tasks = yaml.safe_load((fixture / 'tasks/main.yml').read_text())

        def substitute_privileged_operations(entries):
            for task in entries:
                if 'block' in task:
                    substitute_privileged_operations(task['block'])
                for module in ('file', 'copy', 'template'):
                    action = 'ansible.builtin.' + module
                    if action in task:
                        task[action].pop('owner', None)
                        task[action].pop('group', None)
                if 'ansible.builtin.systemd_service' in task:
                    task.pop('ansible.builtin.systemd_service')
                    task['ansible.builtin.debug'] = {'msg': 'SYSTEMD_RELOADED'}

        substitute_privileged_operations(tasks)
        (fixture / 'tasks/main.yml').write_text(yaml.safe_dump(tasks, sort_keys=False))
        self.env = dict(os.environ, ANSIBLE_NOCOLOR='1',
                        ANSIBLE_COLLECTIONS_PATH=str(self.root / 'collections'),
                        ANSIBLE_HOME=str(self.root / 'ansible-home'),
                        ANSIBLE_LOCAL_TEMP=str(self.root / 'tmp'),
                        PATH=str(fakebin) + os.pathsep + os.environ.get('PATH', ''))

    def tearDown(self):
        self.temporary.cleanup()

    def run_role(self, *, check=False, **overrides):
        values = {
            'ansible_python_interpreter': os.sys.executable,
            'ct_model_storage_mount_path': str(self.mount),
            'ct_model_storage_path': str(self.namespace),
            'ct_model_storage_user': pwd.getpwuid(os.getuid()).pw_name,
            'ct_model_storage_helper_path': str(self.helper),
            'ct_model_storage_systemd_dir': str(self.systemd),
        }
        values.update(overrides)
        playbook = self.root / 'test.yml'
        playbook.write_text(yaml.safe_dump([{
            'hosts': 'localhost', 'gather_facts': False, 'vars': values,
            'roles': ['ktooi.pve_inference.ct_model_storage'],
            'handlers': [{'name': 'Restart fixture', 'ansible.builtin.debug': {'msg': 'RUNTIME_RESTART_NOTIFIED'}}],
        }], sort_keys=False))
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        args = [executable, '-i', 'localhost,', '-c', 'local', str(playbook)]
        if check:
            args.append('--check')
        result = subprocess.run(args, capture_output=True, text=True, timeout=60, env=self.env)
        return result.returncode, result.stdout + result.stderr

    def enabled(self, **overrides):
        return self.run_role(ct_model_storage_enabled=True, ct_model_storage_service_name='fixture.service',
                             ct_model_storage_notify=['Restart fixture'], **overrides)

    def test_disabled_default_is_a_noop(self):
        status, output = self.run_role()
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertFalse(self.helper.exists())
        self.assertFalse(self.systemd.exists())
        self.assertFalse(self.findmnt_calls.exists())

    def test_enabled_role_guards_startup_and_is_idempotent_without_shared_metadata_changes(self):
        before = stat.S_IMODE(self.namespace.stat().st_mode)
        status, output = self.enabled()
        self.assertEqual(status, 0, output)
        unit = self.dropin.read_text()
        self.assertIn('RequiresMountsFor=' + str(self.mount), unit)
        self.assertIn('ExecStartPre=' + str(self.helper) + ' check', unit)
        self.assertIn('--allowed-fstype=nfs --allowed-fstype=nfs4', unit)
        self.assertIn('SYSTEMD_RELOADED', output)
        self.assertIn('RUNTIME_RESTART_NOTIFIED', output)
        self.assertEqual(stat.S_IMODE(self.helper.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(self.namespace.stat().st_mode), before)
        self.assertEqual(list(self.namespace.iterdir()), [self.marker])
        status, output = self.enabled()
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertNotIn('SYSTEMD_RELOADED', output)
        self.assertNotIn('RUNTIME_RESTART_NOTIFIED', output)

    def test_disabling_removes_only_its_dropin_and_preserves_models_and_helper(self):
        status, output = self.enabled()
        self.assertEqual(status, 0, output)
        unrelated = self.dropin.parent / '50-operator.conf'
        unrelated.write_text('[Service]\nEnvironment=UNRELATED=1\n')
        values = {'ct_model_storage_service_name': 'fixture.service', 'ct_model_storage_notify': ['Restart fixture']}
        status, output = self.run_role(**values)
        self.assertEqual(status, 0, output)
        self.assertFalse(self.dropin.exists())
        self.assertTrue(unrelated.is_file())
        self.assertTrue(self.helper.is_file())
        self.assertEqual(self.marker.read_bytes(), b'pre-existing model')
        self.assertIn('SYSTEMD_RELOADED', output)
        self.assertIn('RUNTIME_RESTART_NOTIFIED', output)
        status, output = self.run_role(**values)
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertNotIn('SYSTEMD_RELOADED', output)

    def test_wrong_filesystem_stops_before_startup_guard_installation(self):
        self.state.write_text(json.dumps({'mount': str(self.mount), 'fstype': 'ext4'}))
        status, output = self.enabled()
        self.assertNotEqual(status, 0, output)
        self.assertIn('disallowed filesystem', output)
        self.assertFalse(self.dropin.exists())
        self.assertNotIn('SYSTEMD_RELOADED', output)
        self.assertEqual(list(self.namespace.iterdir()), [self.marker])

    def test_check_mode_does_not_probe_or_create_storage_or_local_files(self):
        status, output = self.enabled(check=True)
        self.assertEqual(status, 0, output)
        self.assertFalse(self.helper.exists())
        self.assertFalse(self.dropin.exists())
        self.assertFalse(self.findmnt_calls.exists())
        self.assertEqual(list(self.namespace.iterdir()), [self.marker])

    def test_invalid_declarations_are_rejected_before_local_writes(self):
        for values in [{'ct_model_storage_enabled': 'false'},
                       {'ct_model_storage_enabled': True, 'ct_model_storage_mount_path': str(self.mount) + '/..'},
                       {'ct_model_storage_enabled': True, 'ct_model_storage_allowed_fstypes': 'nfs'},
                       {'ct_model_storage_enabled': True, 'ct_model_storage_mount_path': str(self.mount) + '\n'},
                       {'ct_model_storage_enabled': True, 'ct_model_storage_allowed_fstypes': ['nfs\n']},
                       {'ct_model_storage_service_name': 'bad/name.service'},
                       {'ct_model_storage_enabled': True, 'ct_model_storage_helper_path': str(self.mount / 'helper')}]:
            with self.subTest(values=values):
                status, output = self.run_role(**values)
                self.assertNotEqual(status, 0, output)
                self.assertFalse(self.helper.exists())
                self.assertFalse(self.systemd.exists())
                self.assertFalse(self.findmnt_calls.exists())

    def test_symlinked_local_parent_is_rejected_before_helper_write(self):
        self.helper.parent.symlink_to(self.namespace, target_is_directory=True)
        status, output = self.enabled()
        self.assertNotEqual(status, 0, output)
        self.assertIn('Symlinks', output)
        self.assertFalse(self.helper.exists())
        self.assertEqual(list(self.namespace.iterdir()), [self.marker])


if __name__ == '__main__':
    unittest.main()
