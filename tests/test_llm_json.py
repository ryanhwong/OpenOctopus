import json

import pytest

from openoctopus.llm_json import first_content, parse_json


def test_plain_json():
    assert parse_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_fenced_no_lang():
    assert parse_json('```\n{"a": 1}\n```') == {"a": 1}


def test_leading_text():
    assert parse_json('Here you go: {"a": 1} done') == {"a": 1}


def test_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_json("not json at all")


def test_null_literal_raises_clear_error():
    with pytest.raises(TypeError, match="non-object"):
        parse_json("null")


def _resp(choices):
    return type("R", (), {"choices": choices})()


def test_first_content_ok():
    msg = type("M", (), {"content": '{"a": 1}'})()
    r = type("R", (), {"choices": [type("C", (), {"message": msg})()]})()
    assert first_content(r) == '{"a": 1}'


def test_first_content_none_choices():
    with pytest.raises(ValueError, match="no choices"):
        first_content(_resp(None))


def test_first_content_empty_choices():
    with pytest.raises(ValueError, match="no choices"):
        first_content(_resp([]))
