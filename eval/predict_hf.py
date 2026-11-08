"""Run a Hugging Face causal LM (the student, or untrained Pythia-70M) on labelled commands.

  python eval/predict_hf.py --model artifacts/models/v1 --out results/student_v1_predictions.jsonl
  python eval/predict_hf.py --model EleutherAI/pythia-70m --out results/pythia_base_predictions.jsonl

Writes {"id", "prediction"} lines with the raw text the model produced, ready for tools/score.py.
Uses the same prompt and decoding as the service (kd/fmt.py).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

from kd import fmt  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True, help='local folder or Hugging Face model id')
    ap.add_argument('--data', default='data/validation.jsonl')
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-new-tokens', type=int, default=64)
    a = ap.parse_args()

    torch.manual_seed(42)
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model).eval()
    rows = [json.loads(x) for x in Path(a.data).read_text(encoding='utf-8').splitlines() if x.strip()]

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(a.out, 'w', encoding='utf-8') as f:
        for r in rows:
            raw = fmt.generate(model, tok, r['text'], a.max_new_tokens)
            f.write(json.dumps({'id': r['id'], 'prediction': raw}, ensure_ascii=False) + '\n')
    print(f'{len(rows)} predictions in {time.time() - t0:.1f}s -> {a.out}')


if __name__ == '__main__':
    main()
