"""Model artefact helper.

  package  --version v1 --src artifacts/models/v1   -> artifacts/release/model-v1.tar.gz + model-v1.sha256
  upload   --version v1 --src artifacts/models/v1   -> s3://models/v1/ (model + tokenizer + model.sha256)
  publish  --version v1 --src artifacts/models/v1   -> package + upload
  base     --dest artifacts/models/pythia-base       -> save untrained EleutherAI/pythia-70m (the "bad" model for the CI gate)
  fetch    --version v1 --dest artifacts/models/v1   -> download the GitHub Release asset, check its SHA-256, unpack
  seed     --versions v1 v2                          -> fetch + upload for every version not yet in s3://models/ (used by make up)

The archive is built deterministically (sorted names, zero timestamps), so the same
files always give the same SHA-256. model.sha256 holds the checksum of the release asset.
"""
import argparse
import gzip
import hashlib
import io
import os
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = os.environ.get('GITHUB_REPO', 'pardhu1502/cloud-kd')
RELEASE_DIR = Path('artifacts/release')


def asset_names(version):
    return f'model-{version}.tar.gz', f'model-{version}.sha256'


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def make_archive(src, dst, top):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(p for p in Path(src).rglob('*') if p.is_file()):
            info = tarfile.TarInfo(f'{top}/{path.relative_to(src).as_posix()}')
            info.size = path.stat().st_size
            info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = 0, 0o644, 0, 0, '', ''
            with open(path, 'rb') as f:
                tar.addfile(info, f)
    with open(dst, 'wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as gz:
        gz.write(buf.getvalue())


def package(version, src):
    tar_name, sha_name = asset_names(version)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    tar_path = RELEASE_DIR / tar_name
    make_archive(src, tar_path, f'model-{version}')
    line = f'{sha256_file(tar_path)}  {tar_name}\n'
    (RELEASE_DIR / sha_name).write_text(line, encoding='utf-8')
    print(f'{tar_path}\n{line.strip()}')
    return line


def upload(version, src, sha_line=None):
    from kd import s3 as s3lib
    s3 = s3lib.client()
    s3lib.upload_dir(s3, src, f's3://models/{version}/')
    sha_line = sha_line or (RELEASE_DIR / asset_names(version)[1]).read_text(encoding='utf-8')
    s3lib.put_text(s3, 'models', f'{version}/model.sha256', sha_line)
    print(f'uploaded {src} to s3://models/{version}/')


def fetch(version, dest):
    tar_name, sha_name = asset_names(version)
    base = f'https://github.com/{REPO}/releases/download/model-{version}'
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = Path(tmp) / tar_name
        print(f'downloading {base}/{tar_name}')
        urllib.request.urlretrieve(f'{base}/{tar_name}', tar_path)
        expected = urllib.request.urlopen(f'{base}/{sha_name}').read().decode().split()[0]
        got = sha256_file(tar_path)
        if got != expected:
            sys.exit(f'checksum mismatch for {tar_name}: {got} != {expected}')
        print(f'sha256 ok {got}')
        with tarfile.open(tar_path) as tar:
            tar.extractall(tmp, filter='data')
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        for p in (Path(tmp) / f'model-{version}').iterdir():
            p.replace(dest / p.name)
    return f'{expected}  {tar_name}\n'


def seed(versions):
    from kd import s3 as s3lib
    s3 = s3lib.client()
    for v in versions:
        if s3lib.list_keys(s3, 'models', f'{v}/config.json'):
            print(f's3://models/{v}/ already there')
            continue
        with tempfile.TemporaryDirectory() as tmp:
            sha_line = fetch(v, tmp)
            upload(v, tmp, sha_line)


def base(dest):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    AutoTokenizer.from_pretrained('EleutherAI/pythia-70m').save_pretrained(dest)
    AutoModelForCausalLM.from_pretrained('EleutherAI/pythia-70m').save_pretrained(dest, safe_serialization=True)
    print(f'saved untrained pythia-70m to {dest}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['package', 'upload', 'publish', 'base', 'fetch', 'seed'])
    ap.add_argument('--version', default='v1')
    ap.add_argument('--versions', nargs='+', default=['v1', 'v2'])
    ap.add_argument('--src')
    ap.add_argument('--dest')
    a = ap.parse_args()
    src = a.src or f'artifacts/models/{a.version}'
    if a.cmd == 'package':
        package(a.version, src)
    elif a.cmd == 'upload':
        upload(a.version, src)
    elif a.cmd == 'publish':
        upload(a.version, src, package(a.version, src))
    elif a.cmd == 'base':
        base(a.dest or 'artifacts/models/pythia-base')
    elif a.cmd == 'fetch':
        fetch(a.version, a.dest or f'artifacts/models/{a.version}')
    elif a.cmd == 'seed':
        seed(a.versions)


if __name__ == '__main__':
    main()
