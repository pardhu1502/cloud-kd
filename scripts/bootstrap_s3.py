"""Create the datasets and models buckets and upload the command pool.

  python scripts/bootstrap_s3.py            (S3_ENDPOINT defaults to http://localhost:8333)
Also: python scripts/bootstrap_s3.py --get s3://datasets/teacher/ results/teacher   (download a prefix)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kd import s3 as s3lib  # noqa: E402

BUCKETS = ('datasets', 'models')


def wait_for_s3(s3, seconds=120):
    deadline = time.time() + seconds
    while True:
        try:
            s3.list_buckets()
            return
        except Exception as e:  # SeaweedFS can take a few seconds after the pod is Ready
            if time.time() > deadline:
                raise SystemExit(f'S3 not reachable: {e}') from e
            time.sleep(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pool', default='data/commands_pool.jsonl')
    ap.add_argument('--get', nargs=2, metavar=('S3_URI', 'DEST'), help='download a prefix and exit')
    a = ap.parse_args()

    s3 = s3lib.client()
    wait_for_s3(s3)
    if a.get:
        files = s3lib.download_prefix(s3, a.get[0], a.get[1])
        print(f'downloaded {len(files)} files to {a.get[1]}')
        return

    existing = {b['Name'] for b in s3.list_buckets().get('Buckets', [])}
    for b in BUCKETS:
        if b not in existing:
            s3.create_bucket(Bucket=b)
            print(f'created bucket {b}')
    s3.upload_file(a.pool, 'datasets', 'commands_pool.jsonl')
    print('uploaded commands_pool.jsonl to s3://datasets/')
    for b in BUCKETS:
        keys = s3lib.list_keys(s3, b, '')
        print(f'{b}: {len(keys)} objects {keys[:5]}')


if __name__ == '__main__':
    main()
