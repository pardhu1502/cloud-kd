"""Call the teacher (phi3.5 on Ollama) with the fixed settings: temperature 0, seed 42."""
import os
from pathlib import Path

import requests

OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')
TEACHER_MODEL = os.environ.get('TEACHER_MODEL', 'phi3.5')
# format=json makes Ollama constrain decoding to JSON; the reply is still stored unedited.
FORMAT_JSON = os.environ.get('TEACHER_FORMAT_JSON', '1') == '1'
OPTIONS = {'temperature': 0, 'seed': 42, 'num_predict': 128}


def load_prompt(path=None):
    path = path or os.environ.get('PROMPT_FILE') or Path(__file__).resolve().parent.parent / 'prompts' / 'teacher_prompt.txt'
    return Path(path).read_text(encoding='utf-8')


def ask(template, command, session=None, timeout=600):
    body = {
        'model': TEACHER_MODEL,
        'prompt': template.replace('{command}', command),
        'stream': False,
        'options': OPTIONS,
    }
    if FORMAT_JSON:
        body['format'] = 'json'
    r = (session or requests).post(f'{OLLAMA_URL}/api/generate', json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()['response']
