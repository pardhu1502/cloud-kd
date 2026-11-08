"""Command-parser inference service.

  POST /parse   {"text": "..."} -> the four-key JSON object (200), or {"error": "invalid_model_output"} (500)
  GET  /healthz 200 while the process is alive
  GET  /readyz  503 until the model is loaded, 200 after

Configuration (environment): MODEL_URI, MODEL_VERSION, S3_ENDPOINT, MAX_NEW_TOKENS, FAULT_INJECT.
S3 credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) come from a Kubernetes Secret.
"""
import json
import logging
import os
import socket
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from kd import fmt  # noqa: E402

log = logging.getLogger('parser')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

SCHEMA = json.loads((ROOT / 'data' / 'schema.json').read_text(encoding='utf-8'))['json_schema']
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


class State:
    model = None
    tokenizer = None
    ready = False


state = State()
_generate_lock = threading.Lock()


def load_model():
    """Download the model and tokenizer from object storage, then load them."""
    from kd import s3 as s3lib

    uri = os.environ['MODEL_URI']
    dest = Path(os.environ.get('MODEL_DIR', '/tmp/model'))
    t0 = time.time()
    s3 = s3lib.client(os.environ['S3_ENDPOINT'])
    files = s3lib.download_prefix(s3, uri, dest, skip_suffixes=('.sha256', '.tar.gz'))
    log.info('downloaded model from %s (%d files) in %.1fs', uri, len(files), time.time() - t0)

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_grad_enabled(False)
    state.tokenizer = AutoTokenizer.from_pretrained(dest)
    state.model = AutoModelForCausalLM.from_pretrained(dest).eval()
    log.info('model %s loaded, ready after %.1fs', os.environ.get('MODEL_VERSION'), time.time() - t0)


def _load_in_background():
    try:
        load_model()
        state.ready = True
    except Exception:
        log.exception('model loading failed, exiting so Kubernetes restarts the pod')
        os._exit(1)


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_load_in_background, daemon=True).start()
    yield


app = FastAPI(title='command parser', lifespan=lifespan)


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


def generate_raw(text):
    with _generate_lock:
        return fmt.generate(state.model, state.tokenizer, text, int(os.environ.get('MAX_NEW_TOKENS', '64')))


def validate(raw):
    """Return the parsed object if it matches schema.json, else None."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if VALIDATOR.is_valid(obj) else None


def response_headers():
    return {'X-Model-Version': os.environ.get('MODEL_VERSION', 'unknown'),
            'X-Served-By': os.environ.get('POD_NAME') or socket.gethostname()}


@app.post('/parse')
def parse(req: ParseRequest):
    headers = response_headers()
    if not state.ready:
        return JSONResponse({'error': 'model_not_ready'}, status_code=503, headers=headers)
    raw = generate_raw(req.text)
    if os.environ.get('FAULT_INJECT') == '1':
        raw = 'not json'
    obj = validate(raw)
    if obj is None:
        log.warning('invalid model output for %r: %r', req.text, raw)
        return JSONResponse({'error': 'invalid_model_output'}, status_code=500, headers=headers)
    return JSONResponse(obj, headers=headers)


@app.get('/healthz')
def healthz():
    return {'status': 'alive'}


@app.get('/readyz')
def readyz():
    if not state.ready:
        return JSONResponse({'status': 'loading'}, status_code=503)
    return {'status': 'ready'}
