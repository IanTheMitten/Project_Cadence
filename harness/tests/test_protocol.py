import pytest

from cadence import protocol as p

ABILITY = {"name": "x", "description": "d", "parameters": {}}


def good(**kw):
    return {**p.hello("lamp1", "device", "lamp", "bedroom", ["audio_in"], [ABILITY]), **kw}


def test_round_trip():
    m = {"type": "ping", "n": 1}
    assert p.decode(p.encode(m)) == m


@pytest.mark.parametrize("text", ["[1]", '{"a":1}', "not json"])
def test_decode_rejects(text):
    with pytest.raises(ValueError):
        p.decode(text)


def test_hello_passes_check():
    m = p.hello("lamp1", "device", "lamp", "bedroom", ["audio_in"], [ABILITY])
    assert p.check_hello(m) is m


def test_bad_version():
    with pytest.raises(ValueError, match="protocol version"):
        p.check_hello(good(version=2))


def test_bad_role():
    with pytest.raises(ValueError):
        p.check_hello(good(role="robot"))


def test_ability_missing_parameters():
    with pytest.raises(ValueError):
        p.check_hello(good(abilities=[{"name": "x", "description": "d"}]))


def test_room_none_ok():
    p.check_hello(good(room=None))
