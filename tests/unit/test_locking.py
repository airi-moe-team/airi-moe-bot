"""Tests del lock de instancia única (2.3)."""

from airi.locking import InstanceLock


def test_second_lock_on_same_path_fails(tmp_path):
    path = tmp_path / ".airi.lock"
    first = InstanceLock(path)
    assert first.acquire() is True

    second = InstanceLock(path)
    assert second.acquire() is False

    first.release()
    third = InstanceLock(path)
    assert third.acquire() is True
    third.release()


def test_release_is_idempotent_and_safe_without_acquire(tmp_path):
    lock = InstanceLock(tmp_path / "x.lock")
    lock.release()  # sin haber adquirido: no debe romper
    assert lock.acquire() is True
    lock.release()
    lock.release()


def test_acquire_creates_parent_directory(tmp_path):
    lock = InstanceLock(tmp_path / "nested" / "dir" / ".airi.lock")

    assert lock.acquire() is True
    assert lock.path.exists()
    lock.release()


def test_context_manager_releases(tmp_path):
    path = tmp_path / ".airi.lock"
    with InstanceLock(path) as lock:
        assert lock.acquire() is True
    # Tras salir del contexto, el lock queda libre.
    assert InstanceLock(path).acquire() is True
