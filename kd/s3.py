"""Small wrapper around boto3 for SeaweedFS (S3 API).

Credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, which are set
from a Kubernetes Secret inside the cluster, or from the git-ignored .env file
on the laptop. Nothing is hard-coded here.
"""
import os
from pathlib import Path

import boto3
from botocore.config import Config


def client(endpoint=None):
    return boto3.client(
        's3',
        endpoint_url=endpoint or os.environ.get('S3_ENDPOINT', 'http://localhost:8333'),
        aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
        region_name='us-east-1',
        config=Config(s3={'addressing_style': 'path'}, retries={'max_attempts': 5}),
    )


def split_uri(uri):
    """s3://bucket/some/prefix -> ('bucket', 'some/prefix')"""
    if not uri.startswith('s3://'):
        raise ValueError(f'not an s3:// uri: {uri}')
    bucket, _, key = uri[5:].partition('/')
    return bucket, key


def get_text(s3, bucket, key):
    return s3.get_object(Bucket=bucket, Key=key)['Body'].read().decode('utf-8')


def put_text(s3, bucket, key, text):
    s3.put_object(Bucket=bucket, Key=key, Body=text.encode('utf-8'))


def list_keys(s3, bucket, prefix):
    keys = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        keys += [o['Key'] for o in page.get('Contents', [])]
    return sorted(keys)


def download_prefix(s3, uri, dest, skip_suffixes=()):
    """Download every object under an s3:// prefix into dest. Returns the file list."""
    bucket, prefix = split_uri(uri)
    prefix = prefix.rstrip('/') + '/' if prefix else ''
    dest = Path(dest)
    got = []
    for key in list_keys(s3, bucket, prefix):
        rel = key[len(prefix):]
        if not rel or rel.endswith('/') or rel.endswith(tuple(skip_suffixes)):
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(target))
        got.append(rel)
    if not got:
        raise FileNotFoundError(f'nothing found under {uri}')
    return got


def upload_dir(s3, src, uri):
    bucket, prefix = split_uri(uri)
    prefix = prefix.rstrip('/')
    for path in sorted(Path(src).rglob('*')):
        if path.is_file():
            key = f'{prefix}/{path.relative_to(src).as_posix()}' if prefix else path.relative_to(src).as_posix()
            s3.upload_file(str(path), bucket, key)
