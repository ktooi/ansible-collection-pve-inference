"""Exercise sd.cpp deployment contracts with local fixtures, without a GPU."""

import grp
import hashlib
import http.server
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import threading
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles/ct_runtime_sdcpp'


class SdcppFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sdcpp-role-')
        self.root = Path(self.temporary.name)
        collection = self.root / 'collections/ansible_collections/ktooi/pve_inference'
        (collection / 'roles').mkdir(parents=True)
        self.role = collection / 'roles/ct_runtime_sdcpp'
        shutil.copytree(ROLE, self.role)
        (collection / 'roles/ct_model_artifacts').symlink_to(
            ROOT / 'roles/ct_model_artifacts', target_is_directory=True)
        (collection / 'roles/ct_runtime_common').symlink_to(
            ROOT / 'roles/ct_runtime_common', target_is_directory=True)
        (collection / 'plugins').symlink_to(ROOT / 'plugins', target_is_directory=True)

        # Build/model tests may notify the real role's handlers. Record their
        # invocation instead of touching the development host's systemd services.
        handlers_file = self.role / 'handlers/main.yml'
        handlers = yaml.safe_load(handlers_file.read_text())
        for handler in handlers:
            actions = [key for key in handler if key.startswith('ansible.builtin.')]
            self.assertEqual(len(actions), 1, handler)
            action = actions[0]
            self.assertIn(action, ['ansible.builtin.systemd',
                                  'ansible.builtin.systemd_service',
                                  'ansible.builtin.service'])
            handler.pop(action)
            handler['ansible.builtin.debug'] = {'msg': 'HANDLER: ' + handler['name']}
        handlers_file.write_text(yaml.safe_dump(handlers, sort_keys=False))

        # Exercise actual configure/build/install behavior on unprivileged CI too.
        # Ownership of the temporary install tree is not the subject of these tests.
        if os.geteuid() != 0:
            build_file = self.role / 'tasks/build.yml'
            build_tasks = yaml.safe_load(build_file.read_text())
            for task in build_tasks:
                for action in ('ansible.builtin.file', 'ansible.builtin.copy'):
                    if action in task:
                        if task[action].get('owner') == 'root':
                            task[action]['owner'] = pwd.getpwuid(os.getuid()).pw_name
                        if task[action].get('group') == 'root':
                            task[action]['group'] = grp.getgrgid(os.getgid()).gr_name
            build_file.write_text(yaml.safe_dump(build_tasks, sort_keys=False))

        self.model = self.root / 'model.safetensors'
        self.model.write_bytes(b'fixture model; not inference weights')
        self.values = {
            'ansible_python_interpreter': os.sys.executable,
            'ansible_user': pwd.getpwuid(os.getuid()).pw_name,
            'ansible_facts': {'distribution': 'Ubuntu', 'distribution_major_version': '24',
                              'distribution_version': '24.04',
                              'os_family': 'Debian', 'architecture': 'x86_64'},
            'ct_runtime_sdcpp_user': pwd.getpwuid(os.getuid()).pw_name,
            'ct_runtime_sdcpp_group': grp.getgrgid(os.getgid()).gr_name,
            'ct_runtime_sdcpp_home': str(self.root / 'home'),
            'ct_runtime_sdcpp_install_dir': str(self.root / 'installed'),
            'ct_runtime_sdcpp_cache_dir': str(self.root / 'cache'),
            'ct_runtime_sdcpp_cuda': False,
            'ct_runtime_sdcpp_backend': 'cpu',
            'ct_runtime_sdcpp_components': {'diffusion_model': str(self.model)},
        }
        self.env = dict(
            os.environ, ANSIBLE_NOCOLOR='1', ANSIBLE_INJECT_FACT_VARS='False',
            ANSIBLE_COLLECTIONS_PATH=str(self.root / 'collections'),
            ANSIBLE_HOME=str(self.root / 'ansible-home'),
            ANSIBLE_LOCAL_TEMP=str(self.root / 'tmp'),
            NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
        self.servers = []

    def tearDown(self):
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join()
        self.temporary.cleanup()

    @staticmethod
    def include(taskfile):
        return {'ansible.builtin.include_role': {
            'name': 'ktooi.pve_inference.ct_runtime_sdcpp',
            'tasks_from': taskfile, 'public': True,
        }}

    def run_tasks(self, tasks, overrides=None, timeout=60, check=False, extra_vars=None):
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable, 'Activate the ansible-core development venv')
        values = {**self.values, **(overrides or {})}
        playbook = self.root / 'test.yml'
        playbook.write_text(yaml.safe_dump([{
            'hosts': 'localhost', 'gather_facts': False, 'vars': values,
            'tasks': tasks,
        }], sort_keys=False))
        command = [executable, '-i', 'localhost,', '-c', 'local', str(playbook)]
        if check:
            command.append('--check')
        if extra_vars is not None:
            variables = self.root / 'extra-vars.yml'
            variables.write_text(yaml.safe_dump(extra_vars))
            command += ['--extra-vars', '@' + str(variables)]
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, env=self.env)
        return result.returncode, result.stdout + result.stderr

    def executable(self, source):
        binary = Path(self.values['ct_runtime_sdcpp_install_dir']) / 'bin/sd-server'
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text(f'#!{os.sys.executable}\n' + source)
        binary.chmod(0o755)
        return binary

    def instrument_build_tools(self, nproc_output='3\n', nproc_status=0):
        """Record actual tool invocations while retaining a real native build."""
        real_cmake = shutil.which('cmake')
        self.assertIsNotNone(real_cmake, 'Install CMake in the development environment')
        tools = self.root / 'build-tools'
        tools.mkdir()
        self.tool_log = self.root / 'build-tools.jsonl'
        self.tool_state = self.root / 'build-tools-state.json'
        self.tool_state.write_text(json.dumps({
            'nproc_output': nproc_output, 'nproc_status': nproc_status,
        }))
        record = (
            'import json, os, sys\n'
            f'with open({str(self.tool_log)!r}, "a") as stream:\n'
            '    stream.write(json.dumps({\n'
            '        "tool": os.path.basename(sys.argv[0]), "argv": sys.argv[1:],\n'
            '        "uid": os.geteuid(),\n'
            '        "build_token": os.environ.get("SDCPP_FIXTURE_BUILD_TOKEN"),\n'
            '        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),\n'
            '        "omp_thread_limit": os.environ.get("OMP_THREAD_LIMIT"),\n'
            '    }) + "\\n")\n'
        )
        scripts = {
            'cmake': record + f'os.execv({real_cmake!r}, [{real_cmake!r}, *sys.argv[1:]])\n',
            'nproc': record + (
                f'with open({str(self.tool_state)!r}) as stream:\n'
                '    state = json.load(stream)\n'
                'sys.stdout.write(state["nproc_output"])\n'
                'sys.exit(state["nproc_status"])\n'
            ),
        }
        for name, source in scripts.items():
            target = tools / name
            target.write_text(f'#!{os.sys.executable}\n' + source)
            target.chmod(0o755)
        environment = {
            'PATH': str(tools) + os.pathsep + os.environ['PATH'],
            'SDCPP_FIXTURE_BUILD_TOKEN': 'service-build-context',
            'OMP_NUM_THREADS': '97',
            'OMP_THREAD_LIMIT': '1',
        }
        self.values['ct_runtime_sdcpp_build_environment'] = environment
        return environment

    def tool_events(self):
        if not self.tool_log.exists():
            return []
        return [json.loads(line) for line in self.tool_log.read_text().splitlines()]

    def http_fixture(self, body, content_type='application/json'):
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        return 'http://127.0.0.1:' + str(server.server_port), requests


class SdcppSettingsTests(SdcppFixture):
    def test_invalid_inputs_stop_before_configuration(self):
        cases = [
            {'ct_runtime_sdcpp_revision': 'main'},
            {'ct_runtime_sdcpp_cuda': 'false'},
            {'ct_runtime_sdcpp_private_tmp': 'false'},
            {'ct_runtime_sdcpp_extra_args': '--steps 8'},
            {'ct_runtime_sdcpp_components': {}},
            {'ct_runtime_sdcpp_components': {'diffusion_model': 'relative/model.gguf'}},
            {'ct_runtime_sdcpp_components': {'unknown_component': str(self.model)}},
            {'ct_runtime_sdcpp_extra_args': ['--backend=cpu']},
            {'ct_runtime_sdcpp_extra_args': ['-l', '0.0.0.0']},
            {'ct_runtime_sdcpp_extra_args': ['-h']},
            {'ct_runtime_sdcpp_extra_args': ['-m', '/tmp/unmanaged.gguf']},
            {'ct_runtime_sdcpp_extra_args': ['--qwen2vl=/tmp/unmanaged.gguf']},
            {'ct_runtime_sdcpp_extra_args': ['--qwen2vl_vision', '/tmp/unmanaged.gguf']},
            {'ct_runtime_sdcpp_extra_args': ['--tae', '/tmp/unmanaged.gguf']},
            {'ct_runtime_sdcpp_install_dir': '/tmp/unsafe-%u'},
            {'ct_runtime_sdcpp_cmake_options': {'SD_USE_UPSTREAM_GGML': 'ON'}},
            {'ct_runtime_sdcpp_artifacts': [{
                'url': 'https://example.invalid/model', 'dest': str(self.model),
                'checksum': 'sha256:not-a-trusted-checksum',
            }]},
            {'ct_runtime_sdcpp_environment': {'BAD=KEY': 'value'}},
            {'ct_runtime_sdcpp_environment': {'VALID_KEY': 'first\nsecond'}},
        ]
        cases.extend({'ct_runtime_sdcpp_build_jobs': value}
                     for value in [0, -1, 1.5, True, False, '', 'AUTO', 'unlimited'])
        for values in cases:
            with self.subTest(values=values):
                status, output = self.run_tasks([
                    self.include('settings.yml'),
                    {'ansible.builtin.debug': {'msg': 'CONFIGURATION_FOLLOW_UP'}},
                ], values)
                self.assertNotEqual(status, 0, output)
                self.assertNotIn('CONFIGURATION_FOLLOW_UP', output)

    def test_service_template_defaults_and_opt_in_preserve_hardening_and_idempotence(self):
        unit = self.root / 'sdcpp.service'
        tasks = [
            self.include('settings.yml'),
            {'ansible.builtin.template': {
                'src': str(self.role / 'templates/sdcpp.service.j2'),
                'dest': str(unit), 'mode': '0644',
            }, 'notify': 'Restart sdcpp'},
        ]
        cases = [
            ({}, 'false', True),
            ({}, 'false', False),
            ({'ct_runtime_sdcpp_private_tmp': True}, 'true', True),
        ]
        for overrides, private_tmp, changed in cases:
            with self.subTest(private_tmp=private_tmp, changed=changed):
                status, output = self.run_tasks(tasks, overrides)
                self.assertEqual(status, 0, output)
                lines = unit.read_text().splitlines()
                self.assertIn('PrivateTmp=' + private_tmp, lines)
                self.assertIn('NoNewPrivileges=true', lines)
                self.assertIn('UMask=0027', lines)
                self.assertIn('User=' + self.values['ct_runtime_sdcpp_user'], lines)
                self.assertIn('Group=' + self.values['ct_runtime_sdcpp_group'], lines)
                if changed:
                    self.assertIn('HANDLER: Restart sdcpp', output)
                else:
                    self.assertIn('changed=0', output)
                    self.assertNotIn('HANDLER: Restart sdcpp', output)

    def test_launcher_preserves_literal_arguments_and_upstream_flag_spelling(self):
        self.executable('import json, sys\nprint(json.dumps(sys.argv[1:]))\n')
        sentinel = self.root / 'must-not-exist'
        prompt = f'with spaces, "quotes", apostrophe\'s, $HOME, $(touch {sentinel}), 100%'
        component = self.root / 'encoder with spaces % and apostrophe\'s.safetensors'
        extra = ['--prompt', prompt, '--sigmas', 'p-h3-image']
        launcher = self.root / 'start-sd-server'
        arguments = self.root / 'argv.json'
        tasks = [
            self.include('settings.yml'),
            {'ansible.builtin.template': {
                'src': str(self.role / 'templates/start-sd-server.sh.j2'),
                'dest': str(launcher), 'mode': '0755',
            }},
            {'ansible.builtin.copy': {
                'content': '{{ ct_runtime_sdcpp_argv | to_json }}',
                'dest': str(arguments), 'mode': '0600',
            }},
        ]
        status, output = self.run_tasks(tasks, {
            'ct_runtime_sdcpp_extra_args': extra,
            'ct_runtime_sdcpp_components': {
                'diffusion_model': str(self.model), 'clip_l': str(component),
                'llm_vision': str(component), 'embeddings_connectors': str(component),
            },
        })
        self.assertEqual(status, 0, output)
        process = subprocess.run([str(launcher)], capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        actual = json.loads(process.stdout)
        self.assertEqual(actual, json.loads(arguments.read_text())[1:])
        self.assertEqual(actual[-len(extra):], extra)
        self.assertIn('--clip_l', actual)
        self.assertIn('--llm_vision', actual)
        self.assertIn('--embeddings-connectors', actual)
        self.assertNotIn('--clip-l', actual)
        self.assertFalse(sentinel.exists())

    def test_check_mode_validates_without_installation_or_network_requests(self):
        url, requests = self.http_fixture(b'fixture model', 'application/octet-stream')
        target = self.root / 'downloaded.safetensors'
        self.instrument_build_tools(nproc_status=91)
        status, output = self.run_tasks([self.include('main.yml')], {
            'ct_runtime_sdcpp_build_jobs': 'auto',
            'ct_runtime_sdcpp_components': {'diffusion_model': str(target)},
            'ct_runtime_sdcpp_artifacts': [{
                'url': url + '/weights', 'dest': str(target),
                'checksum': 'sha256:' + hashlib.sha256(b'fixture model').hexdigest(),
            }],
        }, check=True)
        self.assertEqual(status, 0, output)
        self.assertIn('Check mode validates declarations only', output)
        self.assertFalse(target.exists())
        self.assertFalse(Path(self.values['ct_runtime_sdcpp_cache_dir']).exists())
        self.assertFalse(Path(self.values['ct_runtime_sdcpp_install_dir']).exists())
        self.assertEqual(requests, [])
        self.assertEqual(self.tool_events(), [])

    def test_common_extra_vars_cannot_enable_a_shared_python_environment(self):
        status, output = self.run_tasks([self.include('main.yml')], extra_vars={
            'ct_runtime_common_create_venv': True,
        })
        self.assertNotEqual(status, 0, output)
        self.assertIn('common-role extra-vars must not override', output)
        self.assertFalse(Path(self.values['ct_runtime_sdcpp_home']).exists())
        self.assertFalse(Path(self.values['ct_runtime_sdcpp_cache_dir']).exists())


class SdcppBuildTests(SdcppFixture):
    def create_source(self):
        self.source = self.root / 'native-source'
        self.source.mkdir()
        (self.source / 'CMakeLists.txt').write_text(
            'cmake_minimum_required(VERSION 3.18)\n'
            'project(sdcpp_fixture LANGUAGES CXX)\n'
            'set(FIXTURE_VALUE first CACHE STRING "Fixture build setting")\n'
            'set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")\n'
            'add_executable(sd-server main.cpp)\n'
            'target_compile_definitions(sd-server PRIVATE FIXTURE_VALUE="${FIXTURE_VALUE}")\n')
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True,
                       capture_output=True, text=True)
        return self.commit_source('one')

    def commit_source(self, version, broken=False):
        source = ('#include <iostream>\nint main() { std::cout << "' + version
                  + ':" << FIXTURE_VALUE << "\\n"; }\n')
        (self.source / 'main.cpp').write_text('invalid C++ fixture\n' if broken else source)
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True,
                       capture_output=True, text=True)
        subprocess.run(['git', '-C', str(self.source), '-c', 'user.name=Test Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', version],
                       check=True, capture_output=True, text=True)
        return subprocess.check_output(['git', '-C', str(self.source), 'rev-parse', 'HEAD'],
                                       text=True).strip()

    def build(self, revision, options=None, overrides=None):
        self.assertIsNotNone(shutil.which('cmake'), 'Install CMake in the development environment')
        self.assertIsNotNone(shutil.which('ninja'), 'Install Ninja in the development environment')
        cmake = subprocess.check_output(['cmake', '--version'], text=True)
        compiler = subprocess.check_output(['c++', '--version'], text=True)
        return self.run_tasks([self.include('settings.yml'), self.include('build.yml')], {
            'ct_runtime_sdcpp_repository': str(self.source),
            'ct_runtime_sdcpp_revision': revision,
            'ct_runtime_sdcpp_cmake_options': options or {},
            'ct_runtime_sdcpp_cmake_probe': {'stdout': cmake},
            'ct_runtime_sdcpp_cxx_probe': {'stdout': compiler},
            **(overrides or {}),
        }, timeout=90)

    def installed_output(self):
        binary = Path(self.values['ct_runtime_sdcpp_install_dir']) / 'bin/sd-server'
        return subprocess.check_output([str(binary)], text=True).strip()

    def test_native_build_is_idempotent_and_tracks_options_and_revision(self):
        revision = self.create_source()
        status, output = self.build(revision)
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), 'one:first')
        metadata = Path(self.values['ct_runtime_sdcpp_install_dir']) / 'build.json'
        first = json.loads(metadata.read_text())

        status, output = self.build(revision)
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertNotIn('HANDLER: Restart sdcpp', output)
        self.assertEqual(json.loads(metadata.read_text()), first)

        status, output = self.build(revision, {'FIXTURE_VALUE': 'second'})
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), 'one:second')
        second = json.loads(metadata.read_text())
        self.assertNotEqual(first['build_directory'], second['build_directory'])

        updated_revision = self.commit_source('two')
        status, output = self.build(updated_revision, {'FIXTURE_VALUE': 'second'})
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), 'two:second')
        self.assertEqual(json.loads(metadata.read_text())['revision'], updated_revision)

    def test_failed_compile_preserves_installed_binary_and_does_not_mark_success(self):
        revision = self.create_source()
        status, output = self.build(revision)
        self.assertEqual(status, 0, output)
        failed_revision = self.commit_source('broken', broken=True)
        status, output = self.build(failed_revision)
        self.assertNotEqual(status, 0, output)
        self.assertEqual(self.installed_output(), 'one:first')
        metadata = Path(self.values['ct_runtime_sdcpp_install_dir']) / 'build.json'
        self.assertEqual(json.loads(metadata.read_text())['revision'], revision)
        builds = Path(self.values['ct_runtime_sdcpp_cache_dir']) / 'builds'
        self.assertEqual(len(list(builds.iterdir())), 2)
        self.assertEqual(len(list(builds.glob('*/.ansible-build-complete'))), 1)

    def test_auto_jobs_use_build_context_without_openmp_hints(self):
        revision = self.create_source()
        self.instrument_build_tools()
        status, output = self.build(revision, overrides={
            'ct_runtime_sdcpp_build_jobs': 'auto',
        })
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), 'one:first')
        self.assertIn('Building sd-server with 3 parallel jobs (requested: auto).', output)

        probes = [event for event in self.tool_events() if event['tool'] == 'nproc']
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0]['argv'], [])
        self.assertEqual(probes[0]['uid'], pwd.getpwnam(self.values['ct_runtime_sdcpp_user']).pw_uid)
        self.assertEqual(probes[0]['build_token'], 'service-build-context')
        self.assertIsNone(probes[0]['omp_num_threads'])
        self.assertIsNone(probes[0]['omp_thread_limit'])

        builds = [event for event in self.tool_events()
                  if event['tool'] == 'cmake' and '--build' in event['argv']]
        self.assertEqual(len(builds), 1)
        argv = builds[0]['argv']
        self.assertEqual(argv[argv.index('--parallel') + 1], '3')
        self.assertEqual(builds[0]['uid'], probes[0]['uid'])
        self.assertEqual(builds[0]['build_token'], 'service-build-context')
        self.assertEqual(builds[0]['omp_num_threads'], '97')
        self.assertEqual(builds[0]['omp_thread_limit'], '1')

    def test_fixed_jobs_skip_cpu_probe_and_completed_auto_rerun_is_unchanged(self):
        revision = self.create_source()
        self.instrument_build_tools(nproc_status=92)
        status, output = self.build(revision, overrides={
            'ct_runtime_sdcpp_build_jobs': '4',
        })
        self.assertEqual(status, 0, output)
        self.assertIn('Building sd-server with 4 parallel jobs (requested: 4).', output)
        self.assertEqual(self.installed_output(), 'one:first')
        metadata = Path(self.values['ct_runtime_sdcpp_install_dir']) / 'build.json'
        first = json.loads(metadata.read_text())
        events = self.tool_events()
        self.assertFalse(any(event['tool'] == 'nproc' for event in events))
        builds = [event for event in events
                  if event['tool'] == 'cmake' and '--build' in event['argv']]
        self.assertEqual(len(builds), 1)
        argv = builds[0]['argv']
        self.assertEqual(argv[argv.index('--parallel') + 1], '4')

        status, output = self.build(revision, overrides={
            'ct_runtime_sdcpp_build_jobs': 'auto',
        })
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertNotIn('HANDLER: Restart sdcpp', output)
        self.assertEqual(json.loads(metadata.read_text()), first)
        self.assertEqual(self.tool_events(), events)

    def test_incomplete_build_reuses_objects_with_new_parallel_count(self):
        revision = self.create_source()
        self.instrument_build_tools(nproc_output='5\n')
        status, output = self.build(revision, overrides={
            'ct_runtime_sdcpp_build_jobs': 2,
        })
        self.assertEqual(status, 0, output)
        metadata = Path(self.values['ct_runtime_sdcpp_install_dir']) / 'build.json'
        first = json.loads(metadata.read_text())
        build_directory = Path(first['build_directory'])
        objects = {path: path.stat().st_mtime_ns for path in build_directory.rglob('*.o')}
        self.assertTrue(objects)

        # Simulate a build interrupted after compilation, before link/success.
        (build_directory / '.ansible-build-complete').unlink()
        (build_directory / 'bin/sd-server').unlink()
        status, output = self.build(revision, overrides={
            'ct_runtime_sdcpp_build_jobs': 'auto',
        })
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), 'one:first')
        self.assertEqual(json.loads(metadata.read_text())['build_directory'], str(build_directory))
        self.assertTrue((build_directory / '.ansible-build-complete').exists())
        self.assertEqual({path: path.stat().st_mtime_ns for path in objects}, objects)
        builds = [event for event in self.tool_events()
                  if event['tool'] == 'cmake' and '--build' in event['argv']]
        self.assertEqual(len(builds), 2)
        self.assertEqual([event['argv'][event['argv'].index('--parallel') + 1]
                          for event in builds], ['2', '5'])
        self.assertEqual(len(list(build_directory.parent.iterdir())), 1)

    def test_invalid_cpu_probe_stops_before_compilation(self):
        revision = self.create_source()
        self.instrument_build_tools()
        for stdout, returncode in [('0\n', 0), ('-1\n', 0), ('not-a-count\n', 0),
                                   ('', 0), ('3\n', 93)]:
            with self.subTest(stdout=stdout, returncode=returncode):
                self.tool_state.write_text(json.dumps({
                    'nproc_output': stdout, 'nproc_status': returncode,
                }))
                status, output = self.build(revision, overrides={
                    'ct_runtime_sdcpp_build_jobs': 'auto',
                })
                self.assertNotEqual(status, 0, output)
                self.assertFalse(any(event['tool'] == 'cmake' and '--build' in event['argv']
                                     for event in self.tool_events()))
                self.assertFalse(Path(self.values['ct_runtime_sdcpp_install_dir']).exists())
                self.assertEqual(list(Path(self.values['ct_runtime_sdcpp_cache_dir']).glob(
                    'builds/*/.ansible-build-complete')), [])


class SdcppModelsTests(SdcppFixture):
    def test_artifacts_are_idempotent_and_notify_only_the_sdcpp_handler(self):
        self.executable('print("cpu0 fixture CPU")\n')
        payload = b'fixture downloaded model'
        url, requests = self.http_fixture(payload, 'application/octet-stream')
        target = self.root / 'downloaded.safetensors'
        overrides = {
            'ct_runtime_sdcpp_components': {'diffusion_model': str(target)},
            'ct_runtime_sdcpp_artifacts': [{
                'url': url + '/weights', 'dest': str(target),
                'checksum': 'sha256:' + hashlib.sha256(payload).hexdigest(),
            }],
        }
        tasks = [self.include('settings.yml'), self.include('models.yml')]
        status, output = self.run_tasks(tasks, overrides)
        self.assertEqual(status, 0, output)
        self.assertEqual(target.read_bytes(), payload)
        self.assertIn('HANDLER: Restart sdcpp', output)
        self.assertNotIn('Restart vllm', output)
        count = len(requests)
        status, output = self.run_tasks(tasks, overrides)
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertNotIn('HANDLER: Restart sdcpp', output)
        self.assertEqual(len(requests), count)

    def test_cuda_backend_failure_prevents_model_download(self):
        payload = b'fixture downloaded model'
        url, requests = self.http_fixture(payload, 'application/octet-stream')
        target = self.root / 'must-not-download.safetensors'
        cases = [
            ('cpu0 fixture CPU', 'cuda0', 'could not enumerate the required CUDA devices'),
            ('CUDA0\tfixture GPU', 'diffusion=cuda0&cuda1', 'explicitly selected cudaN'),
        ]
        for devices, backend, message in cases:
            with self.subTest(backend=backend):
                self.executable(f'print({devices!r})\n')
                status, output = self.run_tasks(
                    [self.include('settings.yml'), self.include('models.yml')], {
                        'ct_runtime_sdcpp_cuda': True,
                        'ct_runtime_sdcpp_backend': backend,
                        'ct_runtime_sdcpp_components': {'diffusion_model': str(target)},
                        'ct_runtime_sdcpp_artifacts': [{
                            'url': url + '/weights', 'dest': str(target),
                            'checksum': 'sha256:' + hashlib.sha256(payload).hexdigest(),
                        }],
                    })
                self.assertNotEqual(status, 0, output)
                self.assertIn(message, output)
                self.assertFalse(target.exists())
                self.assertEqual(requests, [])

    def test_global_artifact_extra_vars_cannot_replace_the_runtime_artifacts(self):
        self.executable('print("cpu0 fixture CPU")\n')
        payload = b'fixture downloaded model'
        url, requests = self.http_fixture(payload, 'application/octet-stream')
        target = self.root / 'must-not-download.safetensors'
        status, output = self.run_tasks(
            [self.include('settings.yml'), self.include('models.yml')], {
                'ct_runtime_sdcpp_artifacts': [{
                    'url': url + '/weights', 'dest': str(target),
                    'checksum': 'sha256:' + hashlib.sha256(payload).hexdigest(),
                }],
            }, extra_vars={'ct_model_artifacts': []})
        self.assertNotEqual(status, 0, output)
        self.assertFalse(target.exists())
        self.assertEqual(requests, [])


class SdcppReadinessTests(SdcppFixture):
    def test_http_success_requires_a_loaded_ready_model(self):
        for state in ['ready', 'empty', 'error']:
            with self.subTest(state=state):
                url, requests = self.http_fixture(json.dumps({'state': state}).encode())
                status, output = self.run_tasks([
                    self.include('readiness.yml'),
                    {'ansible.builtin.debug': {'msg': 'READY_FOLLOW_UP'}},
                ], {
                    'ct_runtime_sdcpp_readiness_url': url + '/sdcpp/v1/models/status',
                    'ct_runtime_sdcpp_readiness_retries': 1,
                    'ct_runtime_sdcpp_readiness_delay': 0,
                })
                self.assertEqual(status == 0, state == 'ready', output)
                self.assertEqual('READY_FOLLOW_UP' in output, state == 'ready', output)
                self.assertTrue(requests)
                self.assertEqual(set(requests), {'/sdcpp/v1/models/status'})


if __name__ == '__main__':
    unittest.main()
