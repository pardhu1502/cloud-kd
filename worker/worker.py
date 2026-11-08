"""Teacher labelling worker.

Takes every command whose line number (from 0) % SHARD_COUNT == SHARD_INDEX,
asks the teacher and writes {"id", "text", "teacher_raw"} lines to its own object,
s3://datasets/teacher/shard-<SHARD_INDEX>.jsonl by default.

Labelling on CPU is slow, so the shard object is re-uploaded every
CHECKPOINT_EVERY records and a restarted worker skips ids it already has.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from kd import s3 as s3lib  # noqa: E402
from kd import teacher  # noqa: E402


def select_shard(lines, index, count):
    """Lines whose position (from 0) leaves remainder index when divided by count."""
    if not 0 <= index < count:
        raise ValueError(f'SHARD_INDEX must be in [0, {count}), got {index}')
    return [line for n, line in enumerate(lines) if n % count == index]


def to_jsonl(rows):
    return ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)


def main():
    index = int(os.environ['SHARD_INDEX'])
    count = int(os.environ['SHARD_COUNT'])
    pool_uri = os.environ.get('POOL_URI', 's3://datasets/commands_pool.jsonl')
    out_uri = os.environ.get('OUT_URI', 's3://datasets/teacher/shard-{index}.jsonl').format(index=index)
    every = int(os.environ.get('CHECKPOINT_EVERY', '25'))

    s3 = s3lib.client()
    pool = [json.loads(x) for x in s3lib.get_text(s3, *s3lib.split_uri(pool_uri)).splitlines() if x.strip()]
    mine = select_shard(pool, index, count)
    order = {c['id']: i for i, c in enumerate(mine)}

    out_bucket, out_key = s3lib.split_uri(out_uri)
    done = []
    try:
        done = [json.loads(x) for x in s3lib.get_text(s3, out_bucket, out_key).splitlines() if x.strip()]
    except s3.exceptions.NoSuchKey:
        pass
    done_ids = {r['id'] for r in done}
    print(f'shard {index}/{count}: {len(mine)} commands, {len(done_ids)} already done -> {out_uri}', flush=True)

    template = teacher.load_prompt()
    session = requests.Session()
    start = time.time()
    todo = [c for c in mine if c['id'] not in done_ids]
    for n, cmd in enumerate(todo, 1):
        raw = teacher.ask(template, cmd['text'], session=session)
        done.append({'id': cmd['id'], 'text': cmd['text'], 'teacher_raw': raw})
        if n % every == 0 or n == len(todo):
            # keep pool order so the object looks the same however often the pod restarted
            done.sort(key=lambda r: order[r['id']])
            s3lib.put_text(s3, out_bucket, out_key, to_jsonl(done))
            print(f'shard {index}: {len(done)}/{len(mine)} ({n / (time.time() - start):.2f}/s)', flush=True)
    if not todo:
        print('nothing to do', flush=True)


if __name__ == '__main__':
    main()
