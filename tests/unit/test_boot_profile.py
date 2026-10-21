"""The cold-start boot profile: the number, and the silence it replaces.

A Cloud Run cold start measured 36.9 s on 2026-10-21, of which 33.9 s was a
single undifferentiated block between "Starting new instance" and Python's
first log line. Image pull, interpreter boot and the torch import graph all
live in that block and each has a different fix. `_boot_age_seconds` splits
it: how old the process already was when the first `atlas` module loaded is
pull plus interpreter, and everything after is ours.

It is tested because it is a measurement, and a measurement that silently
returns the wrong thing is how this project has been misled before — the
first version of this instrumentation timed from `atlas.api.asgi` and
reported 0.00 s for the import it existed to measure, because
`atlas.api.__init__` had already pulled the whole graph in.
"""

from __future__ import annotations

import builtins
import io
import os

import atlas


class TestTheBootAgeIsReadFromProcOrRefused:
    @staticmethod
    def _fake_proc(uptime: str, stat: str):
        """Stand in for /proc, and only for /proc."""
        real_open = builtins.open

        def fake_open(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if path == "/proc/uptime":
                return io.StringIO(uptime)
            if path == "/proc/self/stat":
                return io.StringIO(stat)
            return real_open(path, *args, **kwargs)

        return fake_open

    def test_it_subtracts_process_start_from_system_uptime(self, monkeypatch) -> None:
        ticks = os.sysconf("SC_CLK_TCK")
        # Field 22 of /proc/self/stat is starttime in clock ticks. Everything
        # before the "comm" field is skipped by splitting on ") ", so the
        # offset into the remainder is 22 - 3 = 19 — the one piece of this
        # that is easy to get wrong and impossible to notice.
        after_comm = " ".join(["x"] * 19 + [str(40 * ticks)] + ["y"] * 30)
        monkeypatch.setattr(
            builtins, "open", self._fake_proc("500.0 1200.0\n", f"1 (python) {after_comm}")
        )
        assert atlas._boot_age_seconds() == 460.0

    def test_a_command_name_with_spaces_does_not_shift_the_field(self, monkeypatch) -> None:
        # /proc/self/stat's comm field is parenthesised precisely because it
        # can contain spaces and brackets. Splitting on whitespace would put
        # the offset somewhere else entirely and still return a float.
        ticks = os.sysconf("SC_CLK_TCK")
        after_comm = " ".join(["x"] * 19 + [str(10 * ticks)] + ["y"] * 30)
        monkeypatch.setattr(
            builtins,
            "open",
            self._fake_proc("100.0 50.0\n", f"1 (un cold (start)) {after_comm}"),
        )
        assert atlas._boot_age_seconds() == 90.0

    def test_it_returns_none_rather_than_a_number_when_proc_is_absent(
        self, monkeypatch
    ) -> None:
        def no_proc(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise FileNotFoundError(path)

        monkeypatch.setattr(builtins, "open", no_proc)
        # None, not 0.0. A zero here would read as "the image pulled
        # instantly", which is the one conclusion this must never support.
        assert atlas._boot_age_seconds() is None

    def test_unparseable_proc_contents_are_refused_too(self, monkeypatch) -> None:
        monkeypatch.setattr(builtins, "open", self._fake_proc("not-a-number\n", "1 (p) x"))
        assert atlas._boot_age_seconds() is None

    def test_the_import_clock_starts_in_the_root_package(self) -> None:
        # Not in `atlas.api.asgi`: `atlas.api.__init__` imports `create_app`,
        # so a timer started there begins after torch has already loaded.
        assert isinstance(atlas._IMPORT_STARTED, float)
        assert hasattr(atlas, "_BOOT_AGE_AT_IMPORT")
