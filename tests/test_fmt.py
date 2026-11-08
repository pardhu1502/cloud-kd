import json

from kd import fmt


def test_target_keeps_values_and_orders_keys():
    obj = {'place': 'london', 'time': None, 'intent': 'weather_query', 'date': 'today'}
    t = fmt.target(obj)
    assert t.startswith(' {"intent"')
    assert json.loads(t) == obj


def test_prompt_and_first_line():
    assert fmt.prompt('set an alarm') == 'Command: set an alarm\nJSON:'
    assert fmt.first_line(' {"a": 1}\nCommand: next one') == '{"a": 1}'
