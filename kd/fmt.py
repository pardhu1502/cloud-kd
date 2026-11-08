"""Prompt format shared by training, evaluation and the service.

Training example:   "Command: <text>\\nJSON: <teacher json>" + EOS
At inference time the model gets "Command: <text>\\nJSON:" and we keep the first
line it generates.
"""
import json

KEYS = ('intent', 'date', 'time', 'place')
INTENTS = ('alarm_set', 'alarm_query', 'calendar_set', 'calendar_query',
           'calendar_remove', 'weather_query', 'datetime_query', 'recommendation_events')


def prompt(text):
    return f'Command: {text}\nJSON:'


def target(obj):
    """Compact JSON with the keys in schema order. Values are not changed."""
    return ' ' + json.dumps({k: obj[k] for k in KEYS}, ensure_ascii=False)


def first_line(generated):
    return generated.strip().split('\n', 1)[0].strip()


def generate(model, tokenizer, text, max_new_tokens):
    """Greedy decoding. Returns the raw first line produced after 'JSON:'."""
    import torch

    enc = tokenizer(prompt(text), return_tensors='pt')
    with torch.no_grad():
        out = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                             pad_token_id=tokenizer.eos_token_id)
    new_tokens = out[0, enc['input_ids'].shape[1]:]
    return first_line(tokenizer.decode(new_tokens, skip_special_tokens=True))
