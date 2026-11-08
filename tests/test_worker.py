import pytest

from worker.worker import select_shard


@pytest.mark.parametrize('count', [1, 2, 3, 4])
def test_shards_cover_every_line_exactly_once(count):
    lines = list(range(3000))
    shards = [select_shard(lines, i, count) for i in range(count)]
    flat = [x for s in shards for x in s]
    assert sorted(flat) == lines
    assert len(flat) == len(set(flat))


def test_shard_uses_line_number_modulo():
    assert select_shard(['a', 'b', 'c', 'd', 'e'], 1, 2) == ['b', 'd']


def test_bad_shard_index():
    with pytest.raises(ValueError):
        select_shard([1, 2], 2, 2)
