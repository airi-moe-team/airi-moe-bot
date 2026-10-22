"""Bloqueo de instancia única (tarea 2.3)."""

from __future__ import annotations

import os

import pytest

from airi.adapters.instance_lock import InstanceAlreadyRunningError, InstanceLock


def test_second_instance_cannot_acquire(tmp_path):
    path = tmp_path / ".airi.lock"
    first = InstanceLock(path)
    second = InstanceLock(path)
    first.acquire()
    try:
        with pytest.raises(InstanceAlreadyRunningError) as exc:
            second.acquire()
        assert str(os.getpid()) in str(exc.value)
    finally:
        first.release()


def test_release_allows_reacquire(tmp_path):
    path = tmp_path / ".airi.lock"
    lock = InstanceLock(path)
    lock.acquire()
    lock.release()
    again = InstanceLock(path)
    again.acquire()
    again.release()


def test_lock_file_records_owner_pid(tmp_path):
    path = tmp_path / ".airi.lock"
    lock = InstanceLock(path)
    lock.acquire()
    try:
        content = path.read_text(encoding="utf-8")
        assert str(os.getpid()) in content
    finally:
        lock.release()


def test_release_is_idempotent(tmp_path):
    lock = InstanceLock(tmp_path / ".airi.lock")
    lock.release()
    lock.acquire()
    lock.release()
    lock.release()
