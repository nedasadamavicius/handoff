from __future__ import annotations

import sys
import time

import pytest

from handoff.pty_session import PtySession, PtyUnavailable


class TestPtySessionUnspawned:
    """Test behavior of PtySession before spawning."""

    def test_read_before_spawn(self) -> None:
        """read() should return empty bytes before spawning."""
        session = PtySession()
        assert session.read() == b""

    def test_is_alive_before_spawn(self) -> None:
        """is_alive() should return False before spawning."""
        session = PtySession()
        assert session.is_alive() is False

    def test_terminate_before_spawn(self) -> None:
        """terminate() should not raise before spawning."""
        session = PtySession()
        session.terminate()  # Should not raise

    def test_wait_before_spawn(self) -> None:
        """wait() should return None before spawning."""
        session = PtySession()
        assert session.wait() is None


class TestPtySessionSpawned:
    """Test behavior of PtySession after spawning."""

    def test_spawn_and_read_output(self) -> None:
        """Spawn a child that writes output and read it."""
        session = PtySession()
        session.spawn(
            [sys.executable, "-c", "import sys; sys.stdout.write('HELLO_PTY'); sys.stdout.flush()"]
        )

        # Poll for output with timeout
        accumulated = b""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            chunk = session.read()
            if chunk:
                accumulated += chunk
            if b"HELLO_PTY" in accumulated:
                break
            time.sleep(0.05)

        assert b"HELLO_PTY" in accumulated, f"Expected HELLO_PTY in {repr(accumulated)}"
        session.terminate()

    def test_is_alive_and_wait(self) -> None:
        """Test is_alive() and wait() on a short-lived process."""
        session = PtySession()
        session.spawn([sys.executable, "-c", "import sys; sys.exit(0)"])

        # Give it a moment to run
        time.sleep(0.2)

        # Poll until dead
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if not session.is_alive():
                break
            time.sleep(0.05)

        # Once dead, is_alive should be False
        assert session.is_alive() is False

        # wait() should return an int
        status = session.wait()
        assert isinstance(status, int)
        assert status == 0

    def test_write_and_read(self) -> None:
        """Spawn a child that reads stdin and echo it."""
        session = PtySession()
        session.spawn(
            [sys.executable, "-c", "import sys; data = sys.stdin.read(); sys.stdout.write(data); sys.stdout.flush()"]
        )

        # Write some data
        session.write(b"TEST_DATA")

        # Read it back
        accumulated = b""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            chunk = session.read()
            if chunk:
                accumulated += chunk
            if b"TEST_DATA" in accumulated:
                break
            time.sleep(0.05)

        assert b"TEST_DATA" in accumulated, f"Expected TEST_DATA in {repr(accumulated)}"
        session.terminate()

    def test_resize(self) -> None:
        """Test that resize() doesn't raise."""
        session = PtySession()
        session.spawn([sys.executable, "-c", "import time; time.sleep(1)"])
        session.resize(30, 100)  # Should not raise
        session.terminate()

    def test_terminate_idempotent(self) -> None:
        """terminate() should be idempotent."""
        session = PtySession()
        session.spawn([sys.executable, "-c", "import time; time.sleep(10)"])
        session.terminate()
        session.terminate()  # Second call should not raise
