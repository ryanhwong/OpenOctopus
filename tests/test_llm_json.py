import json

import pytest

from openoctopus.llm_json import parse_json


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
