# Subnet plan for 10.20.0.0/16

Rule used: usable hosts = 2^(32 - prefix) - 2. Subnets are allocated from the
largest requirement to the smallest, each one starting right after the previous one.

## Working

| Subnet | Hosts needed | Smallest prefix that fits | Why |
|---|---|---|---|
| app | 1,000 | /22 | /23 gives 2^9 - 2 = 510 (too few); /22 gives 2^10 - 2 = 1,022 |
| public | 250 | /24 | /25 gives 126 (too few); /24 gives 2^8 - 2 = 254 |
| data | 100 | /25 | /26 gives 62 (too few); /25 gives 2^7 - 2 = 126 |
| management | 20 | /27 | /28 gives 14 (too few); /27 gives 2^5 - 2 = 30 |

Placement:

1. **app /22** starts at 10.20.0.0. A /22 is 1,024 addresses = 4 blocks of 256,
   so it covers 10.20.0.0 to 10.20.3.255.
2. **public /24** starts at the next address, 10.20.4.0 (aligned to 256), and covers 10.20.4.0 to 10.20.4.255.
3. **data /25** starts at 10.20.5.0 (aligned to 128) and covers 10.20.5.0 to 10.20.5.127.
4. **management /27** starts at 10.20.5.128 (aligned to 32) and covers 10.20.5.128 to 10.20.5.159.

Everything from 10.20.5.160 to 10.20.255.255 is left free for later.

## Result

| Subnet | Network address | Prefix | Usable host range | Broadcast | Usable hosts |
|---|---|---|---|---|---|
| app | 10.20.0.0 | /22 | 10.20.0.1 - 10.20.3.254 | 10.20.3.255 | 1,022 |
| public | 10.20.4.0 | /24 | 10.20.4.1 - 10.20.4.254 | 10.20.4.255 | 254 |
| data | 10.20.5.0 | /25 | 10.20.5.1 - 10.20.5.126 | 10.20.5.127 | 126 |
| management | 10.20.5.128 | /27 | 10.20.5.129 - 10.20.5.158 | 10.20.5.159 | 30 |

`tests/test_network.py` recomputes this table with Python's `ipaddress` module.

## NACL for the public subnet (network/nacl.json)

Inbound, lowest number first:

| Rule | Protocol | Ports | Source | Action | Purpose |
|---|---|---|---|---|---|
| 50 | all | all | 198.51.100.0/24 | deny | abusive range, blocked even on 80/443 |
| 100 | tcp | 80 | 0.0.0.0/0 | allow | HTTP |
| 110 | tcp | 443 | 0.0.0.0/0 | allow | HTTPS |
| 120 | tcp | 22 | 10.20.5.128/27 | allow | SSH from management only |
| 130 | tcp | 1024-65535 | 10.20.0.0/22 | allow | replies from the app subnet |
| * | all | all | 0.0.0.0/0 | deny | default |

Outbound:

| Rule | Protocol | Ports | Destination | Action | Purpose |
|---|---|---|---|---|---|
| 100 | tcp | 8000 | 10.20.0.0/22 | allow | load balancer to the app |
| 110 | tcp | 1024-65535 | 0.0.0.0/0 | allow | replies to clients |
| * | all | all | 0.0.0.0/0 | deny | default |

Check: `python tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check`

## Why separate reply rules, and why the order matters

A NACL is stateless: it does not remember that a connection was opened. Each
packet, including a reply, is checked against the rules on its own. When a
client connects to port 443, the reply leaves the subnet with the client's
ephemeral port (1024-65535) as its destination port, so it only gets out because
outbound rule 110 allows it. In the same way, when the load balancer calls the
app on port 8000, the app's answer comes back to the load balancer's ephemeral
port, and inbound rule 130 has to let it in. A stateful security group would
allow these replies automatically; a NACL does not.

Rules are evaluated from the lowest number up and the first match decides. A
packet from 198.51.100.9 to port 443 matches both the deny for 198.51.100.0/24
and the allow for 443 from 0.0.0.0/0. The deny only works because its number
(50) is lower than the allow (110). If the deny were numbered, say, 200, rule
110 would match first and the abusive range would reach the web ports.
