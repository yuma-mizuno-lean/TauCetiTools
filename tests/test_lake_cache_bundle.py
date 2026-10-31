import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'tauceti_tools/assets/scripts/lake_cache_bundle.py'
spec = importlib.util.spec_from_file_location('bundle', SCRIPT)
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / 'src'
        self.dst = self.root / 'dst'
        for p in (self.src, self.dst):
            p.mkdir()
            (p / 'lean-toolchain').write_text('leanprover/lean4:v4.36.0-rc1\n')
        self.cache = self.src / '.lake/cache'
        (self.cache / 'outputs/Mei').mkdir(parents=True)
        (self.cache / 'artifacts').mkdir()
        (self.cache / 'outputs/Mei/0123456789abcdef.json').write_text(json.dumps({
            'schemaVersion': '2026-02-25', 'service': None, 'data': 'fedcba9876543210.ltar'}))
        (self.cache / 'artifacts/fedcba9876543210.ltar').write_bytes(b'compressed Lake archive')
        (self.src / '.lake/outputs.jsonl').write_text(
            '"2026-03-17"\n["0123456789abcdef","fedcba9876543210.ltar"]\n')
        self.archive = self.root / 'bundle.tar'

    def test_roundtrip(self):
        bundle.pack(self.src, self.archive, 'Mei')
        bundle.restore(self.dst, self.archive, 'Mei')
        for path in self.cache.rglob('*'):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (self.dst / '.lake/cache' / path.relative_to(self.cache)).read_bytes())

    def test_miss_is_offline_and_does_not_create_cache(self):
        bundle.restore(self.dst, self.archive, 'Mei')
        self.assertFalse((self.dst / '.lake').exists())

    def test_wrong_toolchain_rejected_before_write(self):
        bundle.pack(self.src, self.archive, 'Mei')
        (self.dst / 'lean-toolchain').write_text('different')
        with self.assertRaisesRegex(ValueError, 'policy mismatch'):
            bundle.restore(self.dst, self.archive, 'Mei')
        self.assertFalse((self.dst / '.lake').exists())

    def test_tamper_rejected_before_write(self):
        bundle.pack(self.src, self.archive, 'Mei')
        raw = self.archive.read_bytes().replace(b'compressed Lake archive', b'corrupted! Lake archive')
        self.archive.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            bundle.restore(self.dst, self.archive, 'Mei')
        self.assertFalse((self.dst / '.lake').exists())

    def test_path_traversal_rejected(self):
        with tarfile.open(self.archive, 'w') as tar:
            entry = tarfile.TarInfo('../escape')
            entry.size = 1
            tar.addfile(entry, io.BytesIO(b'x'))
        with self.assertRaisesRegex(ValueError, 'unexpected bundle path'):
            bundle.restore(self.dst, self.archive, 'Mei')

    def test_size_budget(self):
        original = bundle.LIMIT
        try:
            bundle.LIMIT = 1
            with self.assertRaisesRegex(ValueError, 'budget'):
                bundle.pack(self.src, self.archive, 'Mei')
        finally:
            bundle.LIMIT = original


if __name__ == '__main__':
    unittest.main()
