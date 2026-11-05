"""Exercise CT identity checks and lifecycle recovery without a PVE host or API.

Only the API boundary, pct executable, and PVE filesystem paths are substituted.
The real Ansible conditions, rescue flow, stat checks, and config writer run.
"""

import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROLE = Path(__file__).resolve().parents[1] / 'roles/ct_instance'
API_FIXTURE = '''
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule
module = AnsibleModule(argument_spec={
    'failure': {'type': 'str', 'default': ''},
    'marker': {'type': 'str', 'required': True},
})
Path(module.params['marker']).touch()
if module.params['failure']:
    module.fail_json(msg=module.params['failure'])
module.exit_json(changed=False)
'''
EXISTS = "Creation of lxc VM 121 failed: VM 121 already exists on node 'pve-01'"
TIMEOUT = 'Reached timeout while waiting for creating VM'


class CtLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='ct-lifecycle-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.node = self.root / 'nodes/pve-01'
        self.node.mkdir(parents=True)
        (self.root / 'local').symlink_to(self.node, target_is_directory=True)
        self.qemu = self.root / 'qemu-server'
        self.qemu.mkdir()
        self.lxc = self.root / 'lxc'
        self.lxc.mkdir()
        self.config = self.lxc / '121.conf'
        self.api_marker = self.root / 'api-called'
        library = self.root / 'library'
        library.mkdir()
        (library / 'fixture_proxmox.py').write_text(API_FIXTURE)
        self.source = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())

    def source_task(self, name):
        return copy.deepcopy(next(task for task in self.source if task.get('name') == name))

    def guard(self, filename, import_name):
        imported = self.source_task(import_name)
        tasks = yaml.safe_load((ROLE / 'tasks' / filename).read_text())
        for task in tasks:
            if 'ansible.builtin.stat' in task:
                path = task['ansible.builtin.stat']['path']
                task['ansible.builtin.stat']['path'] = str(self.root) + path.removeprefix('/etc/pve')
        return {'name': imported['name'], 'when': imported['when'], 'block': tasks}

    def lifecycle(self, failure=EXISTS):
        reset = self.source_task('Reset CT lifecycle fallback state for this invocation')
        task = self.source_task('Manage CT lifecycle with fallback for an existing local CT')
        api = task['block'][0]
        api.pop('community.general.proxmox')
        api['ansible.legacy.fixture_proxmox'] = {'failure': failure, 'marker': str(self.api_marker)}
        probe = next(item for item in task['rescue'] if 'ansible.builtin.command' in item)
        probe['ansible.builtin.command']['argv'][0] = str(self.root / 'pct')
        return [reset, task]

    def prepare(self):
        return self.guard('target_node.yml', 'Validate the target node before NVIDIA CT lifecycle changes')

    def configure(self):
        guard = self.guard('validate_ct_config.yml',
                           'Validate the local CT configuration before applying NVIDIA passthrough')
        writer = self.source_task('Configure NVIDIA device passthrough in LXC config')
        writer['ansible.builtin.blockinfile']['path'] = str(self.lxc / '{{ ct_instance_vmid }}.conf')
        return [guard, writer, {'ansible.builtin.debug': {'msg': 'CT_CONFIGURED'}}]

    def run_tasks(self, tasks, statuses=None, overrides=None):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        pct = self.root / 'pct'
        pct.write_text(
            f'#!{os.sys.executable}\nimport sys\n'
            f'statuses = {(statuses or {})!r}\n'
            "rc = statuses.get(sys.argv[2], 1)\n"
            "print('status: stopped' if rc == 0 else 'Local LXC config does not exist', "
            "file=sys.stdout if rc == 0 else sys.stderr)\nsys.exit(rc)\n"
        )
        pct.chmod(0o755)
        values = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        values.update(ansible_python_interpreter=os.sys.executable, ansible_become=False,
                      ct_instance_enable_nvidia_passthrough=True, ct_instance_node='pve-01',
                      ct_instance_vmid=121, ct_instance_hostname='ct-image',
                      ct_instance_nvidia_passthrough_block_effective='lxc.test: configured')
        values.update(overrides or {})
        playbook = self.root / 'test.yml'
        playbook.write_text(yaml.safe_dump([{
            'hosts': 'localhost', 'gather_facts': False, 'vars': values, 'tasks': tasks,
        }], sort_keys=False))
        result = subprocess.run(
            [executable, '-i', 'localhost,', '-c', 'local', str(playbook)],
            env=dict(os.environ, ANSIBLE_NOCOLOR='1',
                     ANSIBLE_HOME=str(self.root / 'ansible-home'),
                     ANSIBLE_LOCAL_TEMP=str(self.root / 'tmp'),
                     ANSIBLE_LIBRARY=str(self.root / 'library')),
            text=True, capture_output=True, timeout=60,
        )
        return result.returncode, result.stdout + result.stderr

    def test_qemu_vmid_conflict_stops_before_api_and_config_changes(self):
        vm = self.qemu / '121.conf'
        vm.write_text('name: jail-01\n')
        status, output = self.run_tasks([self.prepare(), *self.lifecycle(), *self.configure()])
        self.assertEqual(status, 2, output)
        self.assertIn('already belongs to a QEMU VM', output)
        self.assertIn('cluster/nextid', output)
        self.assertFalse(self.api_marker.exists())
        self.assertFalse(self.config.exists())
        self.assertEqual(vm.read_text(), 'name: jail-01\n')

    def test_wrong_ssh_node_stops_before_api_and_config_changes(self):
        status, output = self.run_tasks([self.prepare(), *self.lifecycle(), *self.configure()],
                                        overrides={'ct_instance_node': 'pve-02'})
        self.assertEqual(status, 2, output)
        self.assertIn('Align ct_instance_node', output)
        self.assertFalse(self.api_marker.exists())
        self.assertFalse(self.config.exists())

    def test_verified_existing_local_ct_can_be_configured(self):
        self.config.write_text('hostname: ct-image\n')
        status, output = self.run_tasks([self.prepare(), *self.lifecycle(), *self.configure()], {'121': 0})
        self.assertEqual(status, 0, output)
        self.assertIn('CT_CONFIGURED', output)
        self.assertIn('lxc.test: configured', self.config.read_text())

    def test_unverified_allocated_vmid_is_not_treated_as_an_existing_ct(self):
        status, output = self.run_tasks([self.prepare(), *self.lifecycle(), *self.configure()])
        self.assertEqual(status, 2, output)
        self.assertIn('but pct status cannot verify a local LXC CT', output)
        self.assertIn('QEMU VM or a CT on another node', output)
        self.assertNotIn('CT_CONFIGURED', output)
        self.assertFalse(self.config.exists())

    def test_successful_api_result_requires_local_config_before_writing(self):
        status, output = self.run_tasks([self.prepare(), *self.lifecycle(''), *self.configure()])
        self.assertEqual(status, 2, output)
        self.assertIn('No local LXC configuration exists', output)
        self.assertFalse(self.config.exists())

    def test_timeout_fallback_requires_a_verified_ct(self):
        for verified in [False, True]:
            with self.subTest(verified=verified):
                self.config.write_text('hostname: ct-image\n')
                status, output = self.run_tasks([*self.lifecycle(TIMEOUT), *self.configure()],
                                                {'121': 0 if verified else 1})
                self.assertEqual(status, 0 if verified else 2, output)
                self.assertEqual('lxc.test: configured' in self.config.read_text(), verified)

    def test_disabled_timeout_fallback_preserves_the_api_error(self):
        self.config.write_text('hostname: ct-image\n')
        status, output = self.run_tasks([*self.lifecycle(TIMEOUT), *self.configure()], {'121': 0},
                                        {'ct_instance_treat_timeout_as_existing_ct': False})
        self.assertEqual(status, 2, output)
        self.assertIn(TIMEOUT, output)
        self.assertNotIn('CT_CONFIGURED', output)
        self.assertEqual(self.config.read_text(), 'hostname: ct-image\n')

    def test_fallback_state_does_not_leak_to_a_second_ct(self):
        self.config.write_text('hostname: ct-image\n')
        second = self.lxc / '122.conf'
        second.write_text('hostname: ct-stt\n')
        status, output = self.run_tasks([
            *self.lifecycle(),
            {'ansible.builtin.set_fact': {'ct_instance_vmid': 122}},
            *self.lifecycle('Permission check failed for CT 122'),
            *self.configure(),
        ], {'121': 0})
        self.assertEqual(status, 2, output)
        self.assertIn('Permission check failed for CT 122', output)
        self.assertNotIn('CT_CONFIGURED', output)
        self.assertEqual(second.read_text(), 'hostname: ct-stt\n')

    def test_api_only_mode_still_rejects_an_unverified_existing_vmid(self):
        (self.root / 'local').unlink()
        status, output = self.run_tasks([self.prepare(), *self.lifecycle(), *self.configure()],
                                        overrides={'ct_instance_enable_nvidia_passthrough': False})
        self.assertEqual(status, 2, output)
        self.assertIn('but pct status cannot verify a local LXC CT', output)
        self.assertNotIn('CT_CONFIGURED', output)

    def test_absent_ct_does_not_require_a_local_node_link_or_config(self):
        (self.root / 'local').unlink()
        status, output = self.run_tasks([self.prepare(), *self.lifecycle(''), *self.configure()],
                                        overrides={'ct_instance_state': 'absent'})
        self.assertEqual(status, 0, output)
        self.assertTrue(self.api_marker.exists())
        self.assertFalse(self.config.exists())


if __name__ == '__main__':
    unittest.main()
