"""Exercise the opt-in patch lifecycle with real Git, Ansible and CMake.

The small native fixture is not sd.cpp. Only its temporary copy of the patch
bundle is adapted to that fixture's commit and three files; the role tasks and
patch verification helper still execute normally. No GPU or network is used.
"""

import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

import test_sdcpp_runtime as runtime


FLAG = 'ct_runtime_sdcpp_experimental_resolution_patch'


class SdcppResolutionTests(runtime.SdcppFixture):
    build = runtime.SdcppBuildTests.build
    installed_output = runtime.SdcppBuildTests.installed_output

    def metadata(self):
        return Path(self.values['ct_runtime_sdcpp_install_dir']) / 'build.json'

    def create_patch_fixture(self):
        self.source = self.root / 'native-source'
        (self.source / 'examples/server').mkdir(parents=True)
        (self.source / 'CMakeLists.txt').write_text(
            'cmake_minimum_required(VERSION 3.18)\n'
            'project(sdcpp_resolution_fixture LANGUAGES CXX)\n'
            'set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")\n'
            'add_executable(sd-server main.cpp)\n')
        (self.source / 'main.cpp').write_text(
            '#include <iostream>\n'
            '#include "examples/server/runtime.h"\n'
            'int main() { std::cout << k_max_generation_dimension << "\\n"; }\n')
        original = {
            'examples/server/runtime.h': (
                '#pragma once\nconstexpr int k_max_generation_dimension = 4096;\n'),
            'examples/server/runtime.cpp': '// Original runtime fixture.\n',
            'examples/server/routes_sdcpp.cpp': '// Original capability fixture.\n',
        }
        updated = {
            'examples/server/runtime.h': (
                '#pragma once\nconstexpr int k_max_generation_dimension = 8192;\n'),
            'examples/server/runtime.cpp': '// Patched runtime fixture.\n',
            'examples/server/routes_sdcpp.cpp': '// Patched capability fixture.\n',
        }
        for path, content in original.items():
            (self.source / path).write_text(content)
        subprocess.run(['git', 'init', '-q', str(self.source)], check=True,
                       capture_output=True, text=True)
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True,
                       capture_output=True, text=True)
        subprocess.run(['git', '-C', str(self.source), '-c', 'user.name=Test Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '-qm',
                        'Resolution patch fixture'], check=True,
                       capture_output=True, text=True)
        revision = subprocess.check_output(
            ['git', '-C', str(self.source), 'rev-parse', 'HEAD'], text=True).strip()

        self.bundle = self.role / 'files/experimental-resolution'
        manifest_file = self.bundle / 'manifest.json'
        manifest = json.loads(manifest_file.read_text())
        helper = self.bundle / 'apply_sdcpp_limits.py'
        helper.write_text(helper.read_text().replace(manifest['upstream_revision'], revision))
        manifest['upstream_revision'] = revision
        manifest['files'] = []
        hunks = []
        for path, before in original.items():
            after = updated[path]
            hunks.append(f'diff --git a/{path} b/{path}\n')
            hunks.extend(difflib.unified_diff(
                before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile='a/' + path, tofile='b/' + path))
            manifest['files'].append({
                'path': path,
                'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
                'after_sha256': hashlib.sha256(after.encode()).hexdigest(),
            })
        patch = ''.join(hunks).encode()
        (self.bundle / 'sdcpp-resolution.patch').write_bytes(patch)
        manifest['patch_sha256'] = hashlib.sha256(patch).hexdigest()
        manifest_file.write_text(json.dumps(manifest, indent=2) + '\n')
        self.original_header = original['examples/server/runtime.h']
        return revision

    def assert_source_pristine(self):
        checkout = Path(self.values['ct_runtime_sdcpp_cache_dir']) / 'source'
        self.assertEqual((checkout / 'examples/server/runtime.h').read_text(),
                         self.original_header)
        self.assertEqual(subprocess.check_output(
            ['git', '-C', str(checkout), 'status', '--porcelain'], text=True), '')

    def build_events(self):
        return [event for event in self.tool_events()
                if event['tool'] == 'cmake' and '--build' in event['argv']]

    def test_flag_and_revision_are_checked_before_any_deployment(self):
        manifest = json.loads((self.role / 'files/experimental-resolution/manifest.json').read_text())
        self.instrument_build_tools(nproc_status=91)
        cases = [
            ({FLAG: 'false'}, False),
            ({FLAG: 1}, False),
            ({FLAG: True, 'ct_runtime_sdcpp_revision': '0' * 40}, False),
            ({FLAG: True, 'ct_runtime_sdcpp_revision': manifest['upstream_revision']}, True),
        ]
        for overrides, valid in cases:
            with self.subTest(overrides=overrides):
                status, output = self.run_tasks(
                    [self.include('main.yml')], overrides, check=True)
                self.assertEqual(status == 0, valid, output)
                if valid:
                    self.assertIn('Check mode validates declarations only', output)
                self.assertFalse(Path(self.values['ct_runtime_sdcpp_cache_dir']).exists())
                self.assertFalse(Path(self.values['ct_runtime_sdcpp_install_dir']).exists())
                self.assertEqual(self.tool_events(), [])

    def test_toggle_reuses_clean_and_patched_builds_without_reapplying(self):
        revision = self.create_patch_fixture()
        self.instrument_build_tools()
        status, output = self.build(revision)
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), '4096')
        original_metadata = self.metadata().read_bytes()
        original = json.loads(original_metadata)
        self.assertNotIn('resolution_patch', original)

        status, output = self.build(revision, overrides={FLAG: False})
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertEqual(self.metadata().read_bytes(), original_metadata)

        status, output = self.build(revision, overrides={FLAG: True})
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), '8192')
        patched_metadata = self.metadata().read_bytes()
        patched = json.loads(patched_metadata)
        build = Path(patched['build_directory'])
        self.assertNotEqual(str(build), original['build_directory'])
        manifest = json.loads((self.bundle / 'manifest.json').read_text())
        self.assertEqual(patched['resolution_patch']['patch_sha256'], manifest['patch_sha256'])
        self.assertEqual(patched['source_directory'], str(build / 'source'))
        self.assert_source_pristine()
        self.assertEqual(len(self.build_events()), 2)

        status, output = self.build(revision, overrides={FLAG: True})
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        self.assertNotIn('HANDLER: Restart sdcpp', output)
        self.assertEqual(self.metadata().read_bytes(), patched_metadata)
        self.assertEqual(len(self.build_events()), 2)

        # Resume after compilation but before link/completion; retain objects.
        objects = {path: path.stat().st_mtime_ns for path in build.rglob('*.o')}
        self.assertTrue(objects)
        (build / '.ansible-build-complete').unlink()
        (build / 'bin/sd-server').unlink()
        status, output = self.build(revision, overrides={FLAG: True})
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), '8192')
        self.assertEqual({path: path.stat().st_mtime_ns for path in objects}, objects)
        self.assertEqual(self.metadata().read_bytes(), patched_metadata)

        # A new, verified patch payload at the same upstream revision must not
        # reuse an executable compiled with the old patch.
        patch = self.bundle / 'sdcpp-resolution.patch'
        patch.write_text(patch.read_text().replace('8192', '8160'))
        manifest['patch_sha256'] = hashlib.sha256(patch.read_bytes()).hexdigest()
        for record in manifest['files']:
            if record['path'] == 'examples/server/runtime.h':
                updated_header = self.original_header.replace('4096', '8160')
                record['after_sha256'] = hashlib.sha256(updated_header.encode()).hexdigest()
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        status, output = self.build(revision, overrides={FLAG: True})
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), '8160')
        self.assertNotEqual(json.loads(self.metadata().read_text())['build_directory'], str(build))

        builds_before_rollback = len(self.build_events())
        status, output = self.build(revision, overrides={FLAG: False})
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), '4096')
        self.assertEqual(self.metadata().read_bytes(), original_metadata)
        self.assertEqual(len(self.build_events()), builds_before_rollback)
        self.assert_source_pristine()

    def test_failed_build_preserves_install_and_incomplete_copy_is_retried(self):
        revision = self.create_patch_fixture()
        self.instrument_build_tools()
        status, output = self.build(revision)
        self.assertEqual(status, 0, output)
        installed_metadata = self.metadata().read_bytes()
        original_build = Path(json.loads(installed_metadata)['build_directory'])

        # Fail one native build invocation after source preparation, then retry
        # with identical inputs. This simulates an interrupted compiler process.
        fail_next = self.root / 'fail-next-build'
        fail_next.touch()
        wrapper = self.root / 'build-tools/cmake'
        script = wrapper.read_text()
        start = script.index('os.execv(')
        script = (script[:start] + 'from pathlib import Path\n'
                  + f'failure_marker = Path({str(fail_next)!r})\n'
                  + 'if "--build" in sys.argv and failure_marker.exists():\n'
                  + '    failure_marker.unlink()\n    sys.exit(73)\n' + script[start:])
        wrapper.write_text(script)
        status, output = self.build(revision, overrides={FLAG: True})
        self.assertNotEqual(status, 0, output)
        self.assertEqual(self.installed_output(), '4096')
        self.assertEqual(self.metadata().read_bytes(), installed_metadata)
        candidates = [path for path in original_build.parent.iterdir() if path != original_build]
        self.assertEqual(len(candidates), 1)
        build = candidates[0]
        self.assertFalse((build / '.ansible-build-complete').exists())

        # An absent copy marker must discard the incomplete snapshot, including
        # unexpected stale files, and copy the clean Git checkout again.
        (build / '.resolution-source-copied').unlink()
        (build / 'source/main.cpp').unlink()
        (build / 'source/interrupted-copy').write_text('incomplete snapshot\n')
        status, output = self.build(revision, overrides={FLAG: True})
        self.assertEqual(status, 0, output)
        self.assertEqual(self.installed_output(), '8192')
        self.assertFalse((build / 'source/interrupted-copy').exists())
        self.assertTrue((build / '.ansible-build-complete').exists())
        self.assertEqual(json.loads(self.metadata().read_text())['build_directory'], str(build))
        self.assert_source_pristine()

    def test_tampered_bundle_or_snapshot_cannot_replace_installed_binary(self):
        revision = self.create_patch_fixture()
        status, output = self.build(revision)
        self.assertEqual(status, 0, output)
        original_metadata = self.metadata().read_bytes()
        patch = self.bundle / 'sdcpp-resolution.patch'
        correct_patch = patch.read_bytes()
        patch.write_bytes(correct_patch + b'Unexpected change\n')
        status, output = self.build(revision, overrides={FLAG: True})
        self.assertNotEqual(status, 0, output)
        self.assertEqual(self.installed_output(), '4096')
        self.assertEqual(self.metadata().read_bytes(), original_metadata)

        # Disabled deployments do not depend on the experimental bundle.
        status, output = self.build(revision, overrides={FLAG: False})
        self.assertEqual(status, 0, output)
        self.assertIn('changed=0', output)
        patch.write_bytes(correct_patch)
        status, output = self.build(revision, overrides={FLAG: True})
        self.assertEqual(status, 0, output)
        installed_metadata = self.metadata().read_bytes()
        build = Path(json.loads(installed_metadata)['build_directory'])
        header = build / 'source/examples/server/runtime.h'
        header.write_text('Unrecognized source content\n')

        status, output = self.build(revision, overrides={
            FLAG: True, 'ct_runtime_sdcpp_force_rebuild': True,
        })
        self.assertNotEqual(status, 0, output)
        self.assertIn('Unrecognized source content', output)
        self.assertEqual(self.installed_output(), '8192')
        self.assertEqual(self.metadata().read_bytes(), installed_metadata)
        self.assertNotIn('HANDLER: Restart sdcpp', output)
        self.assertFalse((build / '.ansible-build-complete').exists())
        self.assertEqual(header.read_text(), 'Unrecognized source content\n')
        self.assert_source_pristine()


if __name__ == '__main__':
    unittest.main()
