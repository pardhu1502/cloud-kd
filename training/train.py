"""Sequence-level distillation: fine-tune Pythia-70M on the teacher's replies (CPU only).

  python training/train.py --config training/config.yaml [--subset 50]

Each example is "Command: <text>\\nJSON: <teacher json>" + EOS. The loss is only
taken on the JSON part, so the model learns to produce the teacher's reply for a command.
"""
import argparse
import csv
import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402
import transformers  # noqa: E402
import yaml  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer, get_linear_schedule_with_warmup  # noqa: E402

from kd import fmt  # noqa: E402


def set_seed(seed):
    random.seed(seed)
    torch.manual_seed(seed)
    transformers.set_seed(seed)


def check_versions(cfg):
    want = cfg.get('libraries', {})
    have = {'python': f'{sys.version_info.major}.{sys.version_info.minor}',
            'torch': torch.__version__.split('+')[0], 'transformers': transformers.__version__}
    for name, version in want.items():
        if str(version) != have.get(name):
            print(f'WARNING: config pins {name} {version}, installed is {have.get(name)}')
    return have


def load_rows(path, limit):
    rows = [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]
    return rows[:limit]


def encode(rows, tok, max_len):
    examples = []
    for r in rows:
        p = tok(fmt.prompt(r['text']))['input_ids']
        t = tok(fmt.target(json.loads(r['teacher_raw'])))['input_ids'] + [tok.eos_token_id]
        examples.append(((p + t)[:max_len], ([-100] * len(p) + t)[:max_len]))
    return examples


def collate(batch, pad_id):
    width = max(len(ids) for ids, _ in batch)
    ids = torch.full((len(batch), width), pad_id)
    labels = torch.full((len(batch), width), -100)
    mask = torch.zeros((len(batch), width), dtype=torch.long)
    for i, (x, y) in enumerate(batch):
        ids[i, :len(x)] = torch.tensor(x)
        labels[i, :len(y)] = torch.tensor(y)
        mask[i, :len(x)] = 1
    return ids, mask, labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default='training/config.yaml')
    ap.add_argument('--subset', type=int, help='train on the first N records only (smoke test)')
    a = ap.parse_args()
    cfg = yaml.safe_load(Path(a.config).read_text(encoding='utf-8'))

    set_seed(cfg['seed'])
    versions = check_versions(cfg)
    limit = min(a.subset or cfg['max_train_examples'], cfg['max_train_examples'])
    out_dir = Path(cfg['output_dir'] if not a.subset else f'artifacts/models/subset-{a.subset}')
    loss_file = Path(cfg['loss_file'] if not a.subset else 'training/loss_subset.csv')

    tok = AutoTokenizer.from_pretrained(cfg['model_name'], revision=cfg['model_revision'])
    model = AutoModelForCausalLM.from_pretrained(cfg['model_name'], revision=cfg['model_revision'])
    rows = load_rows(cfg['train_file'], limit)
    examples = encode(rows, tok, cfg['max_seq_length'])
    print(f'{len(examples)} training examples from {cfg["train_file"]}')

    bs, epochs = cfg['batch_size'], cfg['epochs']
    steps = math.ceil(len(examples) / bs) * epochs
    opt = torch.optim.AdamW(model.parameters(), lr=float(cfg['learning_rate']), weight_decay=cfg['weight_decay'])
    sched = get_linear_schedule_with_warmup(opt, int(cfg['warmup_ratio'] * steps), steps)
    gen = torch.Generator().manual_seed(cfg['seed'])

    loss_file.parent.mkdir(parents=True, exist_ok=True)
    history = []
    model.train()
    for epoch in range(1, epochs + 1):
        t0, total, n = time.time(), 0.0, 0
        for b in torch.randperm(len(examples), generator=gen).split(bs):
            ids, mask, labels = collate([examples[i] for i in b], tok.eos_token_id)
            loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            total += loss.item()
            n += 1
        history.append((epoch, total / n))
        print(f'epoch {epoch}/{epochs} loss {total / n:.4f} ({time.time() - t0:.0f}s)', flush=True)
        with loss_file.open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['epoch', 'loss'])
            w.writerows((e, f'{v:.6f}') for e, v in history)

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir, safe_serialization=True)
    tok.save_pretrained(out_dir)
    info = {'config': cfg, 'subset': a.subset, 'examples': len(examples), 'versions': versions,
            'final_loss': history[-1][1]}
    (out_dir / 'training_info.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
    print(f'saved model and tokenizer to {out_dir}, loss per epoch in {loss_file}')


if __name__ == '__main__':
    main()
