"""Service tests with the model replaced by a stub (no weights, no S3)."""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from service import app as svc

GOOD = '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'


@pytest.fixture
def client(monkeypatch):
    loaded = threading.Event()
    monkeypatch.setattr(svc, 'load_model', lambda: loaded.wait(5))
    monkeypatch.setattr(svc, 'generate_raw', lambda text: GOOD)
    monkeypatch.setattr(svc.state, 'ready', False)
    monkeypatch.setenv('MODEL_VERSION', 'v1')
    monkeypatch.setenv('POD_NAME', 'parser-abc')
    monkeypatch.delenv('FAULT_INJECT', raising=False)
    with TestClient(svc.app) as c:
        c.finish_loading = lambda: (loaded.set(), _wait_ready())
        yield c


def _wait_ready():
    for _ in range(100):
        if svc.state.ready:
            return
        time.sleep(0.02)
    raise AssertionError('service never became ready')


def test_ready_only_after_model_is_loaded(client):
    assert client.get('/healthz').status_code == 200
    assert client.get('/readyz').status_code == 503
    client.finish_loading()
    assert client.get('/readyz').status_code == 200


def test_parse_returns_only_the_object_and_headers(client):
    client.finish_loading()
    r = client.post('/parse', json={'text': 'what is the weather in london'})
    assert r.status_code == 200
    assert r.json() == {'intent': 'weather_query', 'date': None, 'time': None, 'place': 'london'}
    assert r.headers['X-Model-Version'] == 'v1'
    assert r.headers['X-Served-By'] == 'parser-abc'


def test_fault_inject_gives_500(client, monkeypatch):
    client.finish_loading()
    monkeypatch.setenv('FAULT_INJECT', '1')
    r = client.post('/parse', json={'text': 'what is the weather in london'})
    assert r.status_code == 500
    assert r.json() == {'error': 'invalid_model_output'}


@pytest.mark.parametrize('raw', [
    '{"intent": "weather_query", "date": null, "time": null',          # cut off
    '{"intent": "weather", "date": null, "time": null, "place": null}',  # unknown intent
    '{"intent": "weather_query", "date": null, "time": null}',          # missing key
])
def test_invalid_model_output_never_returns_200(client, monkeypatch, raw):
    client.finish_loading()
    monkeypatch.setattr(svc, 'generate_raw', lambda text: raw)
    r = client.post('/parse', json={'text': 'x'})
    assert r.status_code == 500
    assert r.json() == {'error': 'invalid_model_output'}


def test_parse_before_ready_is_503(client):
    assert client.post('/parse', json={'text': 'x'}).status_code == 503


def test_empty_text_is_rejected(client):
    client.finish_loading()
    assert client.post('/parse', json={'text': ''}).status_code == 422
