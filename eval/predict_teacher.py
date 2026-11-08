"""Run the teacher (phi3.5 on Ollama, same prompt and settings as the labelling workers)
on labelled commands and write {"id", "prediction"} lines for tools/score.py.

  python eval/predict_teacher.py --out results/teacher_validation_predictions.jsonl
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from kd import teacher  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default='data/validation.jsonl')
    ap.add_argument('--out', default='results/teacher_validation_predictions.jsonl')
    a = ap.parse_args()

    template = teacher.load_prompt()
    rows = [json.loads(x) for x in Path(a.data).read_text(encoding='utf-8').splitlines() if x.strip()]
    session = requests.Session()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(a.out, 'w', encoding='utf-8') as f:
        for n, r in enumerate(rows, 1):
            raw = teacher.ask(template, r['text'], session=session)
            f.write(json.dumps({'id': r['id'], 'prediction': raw}, ensure_ascii=False) + '\n')
            if n % 10 == 0:
                print(f'{n}/{len(rows)} ({time.time() - t0:.0f}s)', flush=True)
    print(f'done -> {a.out}')


if __name__ == '__main__':
    main()
