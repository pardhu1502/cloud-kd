import ipaddress
import json
from pathlib import Path

from tools.nacl_sim import decide, load_rules

ROOT = Path(__file__).resolve().parents[1]


def test_subnet_plan():
    # largest first, smallest prefix that fits, packed from 10.20.0.0
    need = [('app', 1000), ('public', 250), ('data', 100), ('management', 20)]
    start = int(ipaddress.ip_address('10.20.0.0'))
    plan = {}
    for name, hosts in need:
        prefix = max(p for p in range(1, 31) if 2 ** (32 - p) - 2 >= hosts)
        net = ipaddress.ip_network(f'{ipaddress.ip_address(start)}/{prefix}')
        plan[name] = net
        start = int(net.broadcast_address) + 1
    assert {k: str(v) for k, v in plan.items()} == {
        'app': '10.20.0.0/22', 'public': '10.20.4.0/24', 'data': '10.20.5.0/25', 'management': '10.20.5.128/27'}
    assert [plan[k].num_addresses - 2 for k in plan] == [1022, 254, 126, 30]
    text = (ROOT / 'network' / 'subnets.md').read_text(encoding='utf-8')
    for net in plan.values():
        assert str(net.broadcast_address) in text


def check(rules, direction, port, address, proto='tcp'):
    return decide(rules, {'direction': direction, 'protocol': proto, 'port': port, 'address': address})[0]


def test_nacl_sample_packets():
    rules = load_rules(ROOT / 'network' / 'nacl.json')
    for line in (ROOT / 'network' / 'packets_sample.jsonl').read_text().splitlines():
        p = json.loads(line)
        assert decide(rules, p)[0] == p['expected'], p['id']


def test_nacl_policy():
    r = load_rules(ROOT / 'network' / 'nacl.json')
    assert check(r, 'inbound', 80, '203.0.113.5') == 'allow'
    assert check(r, 'inbound', 443, '198.51.100.200') == 'deny'
    assert check(r, 'inbound', 80, '198.51.100.1') == 'deny'
    assert check(r, 'inbound', 22, '10.20.5.130') == 'allow'
    assert check(r, 'inbound', 22, '10.20.5.20') == 'deny'      # data subnet, not management
    assert check(r, 'inbound', 22, '10.20.1.9') == 'deny'
    assert check(r, 'inbound', 40000, '10.20.2.7') == 'allow'   # reply from app
    assert check(r, 'inbound', 40000, '203.0.113.5') == 'deny'
    assert check(r, 'inbound', 53, '8.8.8.8', 'udp') == 'deny'
    assert check(r, 'outbound', 8000, '10.20.3.254') == 'allow'
    # stateless: 8000 is also inside the clients' ephemeral range, so the reply rule lets it out
    assert check(r, 'outbound', 8000, '203.0.113.5') == 'allow'
    assert check(r, 'outbound', 22, '10.20.5.130') == 'deny'
    assert check(r, 'outbound', 443, '203.0.113.5') == 'deny'
    assert check(r, 'outbound', 1024, '203.0.113.5') == 'allow'
    assert check(r, 'outbound', 1023, '203.0.113.5') == 'deny'
