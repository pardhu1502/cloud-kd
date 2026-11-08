"""Clean the teacher's shard outputs into datasets/v1/train.jsonl.

Every input record gets exactly one outcome, checked in this order:
  (a) invalid_json      reply is not valid JSON
  (b) wrong_keys        reply is not an object with exactly intent, date, time, place
  (c) bad_intent        intent is not one of the eight
  (d) bad_slot          a slot is neither null nor non-empty text found in the command
  (e) duplicate         same command text as an earlier (smaller id) record that passed (a)-(d)
      kept
So input = a + b + c + d + duplicates + kept.

Kept records are written unchanged ({"id", "text", "teacher_raw"}) in id order,
and the SHA-256 of the file goes to train.sha256.

  python worker/clean.py                         # read s3://datasets/teacher/, write s3://datasets/v1/
  python worker/clean.py --local-dir results/teacher --no-upload
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kd.fmt import INTENTS, KEYS  # noqa: E402

REASONS = ('invalid_json', 'wrong_keys', 'bad_intent', 'bad_slot', 'duplicate')


def id_key(rec):
    return (len(rec['id']), rec['id'])


def reject_reason(rec):
    """Return one of (a)-(d) as a string, or None if the reply is usable."""
    try:
        obj = json.loads(rec['teacher_raw'])
    except (json.JSONDecodeError, TypeError):
        return 'invalid_json'
    if not isinstance(obj, dict) or set(obj) != set(KEYS):
        return 'wrong_keys'
    if obj['intent'] not in INTENTS:
        return 'bad_intent'
    text = rec['text'].lower()
    for k in ('date', 'time', 'place'):
        v = obj[k]
        if v is None:
            continue
        if not isinstance(v, str) or not v.strip() or v.lower() not in text:
            return 'bad_slot'
    return None


def clean(records):
    """Return (kept records in id order, counts dict)."""
    ids = [r['id'] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError('the same id appears more than once across the shards')
    counts = {'input': len(records), **{r: 0 for r in REASONS}, 'kept': 0}
    kept, seen_texts = [], set()
    for rec in sorted(records, key=id_key):
        reason = reject_reason(rec)
        if reason is None and rec['text'] in seen_texts:
            reason = 'duplicate'
        if reason:
            counts[reason] += 1
            continue
        seen_texts.add(rec['text'])
        kept.append({'id': rec['id'], 'text': rec['text'], 'teacher_raw': rec['teacher_raw']})
    counts['kept'] = len(kept)
    assert counts['input'] == sum(counts[r] for r in REASONS) + counts['kept']
    return kept, counts


def to_bytes(rows):
    return ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode('utf-8')


def parse_jsonl(text):
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--shards-uri', default='s3://datasets/teacher/')
    ap.add_argument('--local-dir', help='read shard-*.jsonl from this folder instead of S3')
    ap.add_argument('--out-uri', default='s3://datasets/v1/')
    ap.add_argument('--out-dir', default='data/v1', help='local copy (committed) of train.jsonl and train.sha256')
    ap.add_argument('--pool', default='data/commands_pool.jsonl', help='check every pool id is in exactly one shard')
    ap.add_argument('--counts', default='results/clean_counts.json')
    ap.add_argument('--no-upload', action='store_true')
    a = ap.parse_args()

    s3 = None
    if a.local_dir:
        shard_texts = {p.name: p.read_text(encoding='utf-8') for p in sorted(Path(a.local_dir).glob('shard-*.jsonl'))}
    else:
        from kd import s3 as s3lib
        s3 = s3lib.client()
        bucket, prefix = s3lib.split_uri(a.shards_uri)
        shard_texts = {k: s3lib.get_text(s3, bucket, k) for k in s3lib.list_keys(s3, bucket, prefix) if k.endswith('.jsonl')}
    if not shard_texts:
        sys.exit('no shard files found')

    records = []
    for name, text in shard_texts.items():
        rows = parse_jsonl(text)
        print(f'{name}: {len(rows)} records')
        records += rows

    if a.pool and Path(a.pool).exists():
        pool_ids = {json.loads(x)['id'] for x in Path(a.pool).read_text(encoding='utf-8').splitlines() if x.strip()}
        got = [r['id'] for r in records]
        missing, extra = pool_ids - set(got), set(got) - pool_ids
        print(f'coverage: {len(pool_ids)} pool ids, {len(missing)} missing, {len(got) - len(set(got))} repeated, {len(extra)} unknown')

    kept, counts = clean(records)
    data = to_bytes(kept)
    digest = hashlib.sha256(data).hexdigest()
    sha_line = f'{digest}  train.jsonl\n'

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'train.jsonl').write_bytes(data)
    (out / 'train.sha256').write_text(sha_line, encoding='utf-8')
    Path(a.counts).parent.mkdir(parents=True, exist_ok=True)
    Path(a.counts).write_text(json.dumps({**counts, 'sha256': digest}, indent=2) + '\n', encoding='utf-8')

    if not a.no_upload:
        from kd import s3 as s3lib
        s3 = s3 or s3lib.client()
        bucket, prefix = s3lib.split_uri(a.out_uri)
        prefix = prefix.rstrip('/')
        s3.put_object(Bucket=bucket, Key=f'{prefix}/train.jsonl', Body=data)
        s3lib.put_text(s3, bucket, f'{prefix}/train.sha256', sha_line)
        print(f'uploaded to {a.out_uri}')

    print(json.dumps(counts, indent=2))
    print(f'sha256 {digest}')


if __name__ == '__main__':
    main()
