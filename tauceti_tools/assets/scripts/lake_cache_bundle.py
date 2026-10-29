#!/usr/bin/env python3
"""Offline, bounded transport of standard Lake records and archives."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

LIMIT = 64 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{16}")
ARCHIVE = re.compile(r"[0-9a-f]{16}\.ltar")


def pack(project, bundle, package):
    cache = project / '.lake/cache'
    lines = (project / '.lake/outputs.jsonl').read_text().splitlines()
    if json.loads(lines[0]) != '2026-03-17':
        raise ValueError('unsupported Lake map schema')
    entries = [json.loads(line) for line in lines[1:]]
    if not entries or len(entries) > 10000:
        raise ValueError('invalid output count')
    files = {}
    for inp, archive in entries:
        if not HASH.fullmatch(inp) or not ARCHIVE.fullmatch(archive):
            raise ValueError('invalid Lake mapping')
        record = cache / 'outputs' / package / (inp + '.json')
        if record.is_symlink():
            raise ValueError('symlink record')
        raw = record.read_bytes()
        obj = json.loads(raw)
        if obj.get('schemaVersion') != '2026-02-25':
            raise ValueError('unsupported Lake output record')
        # A local build records individual .olean/.ilean/.c outputs. Lake's
        # own `build -o` map identifies their packed .ltar. Transport the same
        # archive-reference form that native `lake cache get` installs.
        files[f'outputs/{package}/{inp}.json'] = json.dumps({
            'schemaVersion': '2026-02-25', 'service': None, 'data': archive,
        }).encode()
        path = cache / 'artifacts' / archive
        if path.is_symlink():
            raise ValueError('symlink archive')
        files['artifacts/' + archive] = path.read_bytes()
    if sum(map(len, files.values())) > LIMIT:
        raise ValueError('bundle exceeds 64 MiB budget')
    meta = dict(version=1, package=package, toolchain=(project/'lean-toolchain').read_text().strip(),
                files={name: dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()) for name,raw in files.items()})
    files['manifest.json'] = json.dumps(meta).encode()
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle, 'w:') as output:
        for name, raw in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            member.mode = 0o600
            output.addfile(member, io.BytesIO(raw))
    if bundle.stat().st_size > LIMIT:
        bundle.unlink()
        raise ValueError('packed bundle exceeds 64 MiB budget')
    print(f'Packed {len(entries)} Lake records; bundle_bytes={bundle.stat().st_size}; Mei Cloudflare requests=0')


def restore(project, bundle, package):
    if not bundle.exists():
        print('Bundle miss; build missing outputs locally. Mei Cloudflare requests=0')
        return
    if bundle.stat().st_size > LIMIT:
        raise ValueError('oversized bundle')
    files = {}
    with tarfile.open(bundle, 'r:') as source:
        total = 0
        for member in source:
            total += member.size
            if not member.isfile() or member.name in files or total > LIMIT or len(files) > 20000:
                raise ValueError('unsafe bundle member')
            allowed = (member.name == 'manifest.json' or
                       re.fullmatch(r'artifacts/[0-9a-f]{16}\.ltar', member.name) or
                       re.fullmatch(r'outputs/' + re.escape(package) + r'/[0-9a-f]{16}\.json', member.name))
            if not allowed:
                raise ValueError('unexpected bundle path')
            files[member.name] = source.extractfile(member).read()
    meta = json.loads(files.pop('manifest.json'))
    if (meta.get('version') != 1 or meta.get('package') != package or
            meta.get('toolchain') != (project/'lean-toolchain').read_text().strip() or
            set(meta['files']) != set(files)):
        raise ValueError('bundle policy mismatch')
    for name, raw in files.items():
        if meta['files'][name] != dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest()):
            raise ValueError('bundle digest mismatch')
        if name.startswith('outputs/'):
            record = json.loads(raw)
            if (record.get('schemaVersion') != '2026-02-25' or
                    not ARCHIVE.fullmatch(record.get('data', '')) or
                    'artifacts/' + record['data'] not in files):
                raise ValueError('unresolved Lake output record')
    cache = project / '.lake/cache'
    for name, raw in files.items():
        path = cache / name
        if any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError('symlink cache destination')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    count = sum(name.startswith('outputs/') for name in files)
    print(f'Restored {count} standard Lake records from one bundle; Mei Cloudflare requests=0')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['pack','restore'])
    parser.add_argument('project', type=Path)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--package', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.package):
        raise SystemExit('invalid package')
    globals()[args.operation](args.project.resolve(), args.bundle.resolve(), args.package)
