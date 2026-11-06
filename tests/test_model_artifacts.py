"""Validate model declarations without fetching user assets."""

import importlib.util
from pathlib import Path
import unittest

from ansible.errors import AnsibleFilterError

PATH = Path(__file__).resolve().parents[1] / 'plugins/filter/model_artifacts.py'
SPEC = importlib.util.spec_from_file_location('artifact_filters', PATH)
FILTERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILTERS)


class ArtifactDeclarationTests(unittest.TestCase):
    def asset(self, **overrides):
        return dict(url='https://example.invalid/weights', dest='/opt/inference/model/weights',
                    checksum='sha256:' + 'a' * 64, **overrides)

    def test_missing_hash_and_ambiguous_destinations_are_rejected(self):
        invalid = [
            {'url': 'https://example.invalid/source', 'dest': '/tmp/model'},
            {'url': 'file:///etc/passwd', 'dest': '/tmp/model', 'checksum': 'sha256:' + 'a' * 64},
            {'url': 'https://example.invalid/source', 'dest': '/tmp/../model', 'checksum': 'sha256:' + 'a' * 64},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(AnsibleFilterError):
                FILTERS.model_artifacts_validate([value])
        duplicate = self.asset()
        with self.assertRaisesRegex(AnsibleFilterError, 'unique'):
            FILTERS.model_artifacts_validate([duplicate, dict(duplicate, dest='/opt//inference/model/weights')])

    def test_invalid_source_details_are_not_in_validation_errors(self):
        source = 'https://example.invalid/private source?token=fixture'
        with self.assertRaises(AnsibleFilterError) as raised:
            FILTERS.model_artifacts_validate([dict(self.asset(), url=source)])
        self.assertNotIn(source, str(raised.exception))
        self.assertNotIn('token=', str(raised.exception))

    def test_hashes_are_normalized_and_unknown_options_fail(self):
        result = FILTERS.model_artifacts_validate([dict(self.asset(), checksum='sha256:' + 'A' * 64)])
        self.assertEqual(result[0]['checksum'], 'sha256:' + 'a' * 64)
        with self.assertRaises(AnsibleFilterError):
            FILTERS.model_artifacts_validate([dict(self.asset(), checkum='typo')])

    def test_lora_aliases_and_paths_are_safe_for_core_arguments(self):
        for adapter in [
            {'name': '--option', 'path': '/opt/adapter'},
            {'name': 'adapter-01', 'path': '/opt/adapter;echo'},
            {'name': 'adapter-01', 'path': '/opt/adapter', 'scale': 0.8},
        ]:
            with self.subTest(adapter=adapter), self.assertRaises(AnsibleFilterError):
                FILTERS.vllm_lora_adapters_validate([adapter], 'core')
        with self.assertRaisesRegex(AnsibleFilterError, 'unique'):
            FILTERS.vllm_lora_adapters_validate([{'name': 'same', 'path': '/one'}, {'name': 'same', 'path': '/two'}], 'omni')

    def test_omni_requests_keep_scale_and_server_paths_without_source_metadata(self):
        adapters = FILTERS.vllm_lora_adapters_validate([
            {'name': 'adapter-01', 'path': '/opt/inference/adapter-01', 'scale': 0.8},
            {'name': 'adapter-02', 'path': '/opt/inference/adapter-02'},
        ], 'omni')
        self.assertEqual(FILTERS.vllm_lora_requests(adapters)['adapter-01'], {
            'name': 'adapter-01', 'local_path': '/opt/inference/adapter-01', 'scale': 0.8})
        self.assertEqual(adapters[1]['scale'], 1.0)
        for bad in [float('nan'), float('inf'), -1, True, '1.0', 10 ** 1000]:
            with self.subTest(scale=bad), self.assertRaises(AnsibleFilterError):
                FILTERS.vllm_lora_adapters_validate([{'name': 'adapter', 'path': '/opt/adapter', 'scale': bad}], 'omni')


if __name__ == '__main__':
    unittest.main()
