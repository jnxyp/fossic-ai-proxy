"""Tests for repeat-request upgrade detection."""
from __future__ import annotations

import time
from unittest.mock import patch

import upgrade


def _clear():
    upgrade._cache.clear()


MESSAGES = [{"role": "user", "content": "Translate this."}]
MESSAGES_ALT = [{"role": "user", "content": "Different text."}]


def test_first_request_not_a_repeat():
    _clear()
    assert upgrade.check_and_record("sk-key", MESSAGES, window=15) is False


def test_second_identical_request_is_repeat():
    _clear()
    upgrade.check_and_record("sk-key", MESSAGES, window=15)
    assert upgrade.check_and_record("sk-key", MESSAGES, window=15) is True


def test_different_messages_not_a_repeat():
    _clear()
    upgrade.check_and_record("sk-key", MESSAGES, window=15)
    assert upgrade.check_and_record("sk-key", MESSAGES_ALT, window=15) is False


def test_different_key_not_a_repeat():
    _clear()
    upgrade.check_and_record("sk-key-a", MESSAGES, window=15)
    assert upgrade.check_and_record("sk-key-b", MESSAGES, window=15) is False


def test_expired_entry_not_a_repeat():
    _clear()
    past = time.monotonic() - 20
    upgrade._cache[("sk-key", None, upgrade._messages_hash(MESSAGES))] = past
    assert upgrade.check_and_record("sk-key", MESSAGES, window=15) is False


def test_repeat_within_window_is_detected():
    _clear()
    now = time.monotonic()
    upgrade._cache[("sk-key", None, upgrade._messages_hash(MESSAGES))] = now - 5
    assert upgrade.check_and_record("sk-key", MESSAGES, window=15) is True


def test_expired_entries_pruned():
    _clear()
    past = time.monotonic() - 20
    upgrade._cache[("sk-old", None, "hash")] = past
    upgrade.check_and_record("sk-key", MESSAGES, window=15)
    assert ("sk-old", None, "hash") not in upgrade._cache


def test_different_ip_not_a_repeat():
    _clear()
    upgrade.check_and_record("sk-key", MESSAGES, window=15, client_ip="1.2.3.4")
    assert upgrade.check_and_record("sk-key", MESSAGES, window=15, client_ip="5.6.7.8") is False


def test_same_ip_is_repeat():
    _clear()
    upgrade.check_and_record("sk-key", MESSAGES, window=15, client_ip="1.2.3.4")
    assert upgrade.check_and_record("sk-key", MESSAGES, window=15, client_ip="1.2.3.4") is True


def test_no_ip_different_clients_trigger_each_other():
    """When upgrade_use_ip=False (client_ip=None), all clients sharing a key
    are treated as one — a request from any client counts as a repeat."""
    _clear()
    upgrade.check_and_record("sk-key", MESSAGES, window=15, client_ip=None)
    assert upgrade.check_and_record("sk-key", MESSAGES, window=15, client_ip=None) is True
