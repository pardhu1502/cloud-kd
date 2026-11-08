import json

import pytest

from worker.clean import clean, reject_reason, to_bytes


def rec(id_, text, raw):
    return {'id': id_, 'text': text, 'teacher_raw': raw if isinstance(raw, str) else json.dumps(raw)}


GOOD = {'intent': 'weather_query', 'date': None, 'time': None, 'place': 'london'}


@pytest.mark.parametrize('raw, reason', [
    ('{"intent": "weather_query", "date": null', 'invalid_json'),
    ('```json\n{}\n```', 'invalid_json'),
    ({'intent': 'weather_query', 'date': None, 'time': None}, 'wrong_keys'),
    ({**GOOD, 'extra': 1}, 'wrong_keys'),
    (['weather_query'], 'wrong_keys'),
    ({**GOOD, 'intent': 'weather'}, 'bad_intent'),
    ({**GOOD, 'place': 'paris'}, 'bad_slot'),
    ({**GOOD, 'time': '07:00'}, 'bad_slot'),
    ({**GOOD, 'date': ''}, 'bad_slot'),
    ({**GOOD, 'date': 5}, 'bad_slot'),
    (GOOD, None),
])
def test_reject_reasons(raw, reason):
    assert reject_reason(rec('C0001', 'what is the weather in london', raw)) == reason


def test_counts_add_up_and_duplicates_keep_smallest_id():
    records = [
        rec('C0010', 'what is the weather in london', GOOD),
        rec('C0002', 'what is the weather in london', GOOD),       # same text, smaller id -> kept
        rec('C0003', 'what is the weather in london', 'not json'),  # rejected before the duplicate check
        rec('C0004', 'set an alarm', {'intent': 'alarm_set', 'date': None, 'time': None}),
        rec('C0005', 'set an alarm for six am', {'intent': 'alarm_set', 'date': None, 'time': 'six am', 'place': None}),
    ]
    kept, counts = clean(records)
    assert [r['id'] for r in kept] == ['C0002', 'C0005']
    assert counts == {'input': 5, 'invalid_json': 1, 'wrong_keys': 1, 'bad_intent': 0,
                      'bad_slot': 0, 'duplicate': 1, 'kept': 2}


def test_output_is_deterministic_and_in_id_order():
    records = [rec('C0100', 'what time is it in tokyo', {'intent': 'datetime_query', 'date': None, 'time': None, 'place': 'tokyo'}),
               rec('C0009', 'what is the weather in london', GOOD)]
    a, _ = clean(records)
    b, _ = clean(list(reversed(records)))
    assert to_bytes(a) == to_bytes(b)
    assert [r['id'] for r in a] == ['C0009', 'C0100']


def test_repeated_id_across_shards_is_an_error():
    with pytest.raises(ValueError):
        clean([rec('C0001', 'a', GOOD), rec('C0001', 'a', GOOD)])
