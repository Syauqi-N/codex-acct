"""Tests for codex-acct. Run with: python3 -m unittest discover tests"""
import base64
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from io import StringIO
from unittest import mock

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "codex-acct")
_loader = SourceFileLoader("codex_acct", SCRIPT)
ca = module_from_spec(spec_from_loader("codex_acct", _loader))
_loader.exec_module(ca)


def make_threads_db(path, ids):
    with closing(sqlite3.connect(path)) as con:
        con.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT)")
        con.executemany("INSERT INTO threads VALUES (?, ?)", [(i, i) for i in ids])
        con.commit()


def thread_ids(path):
    with closing(sqlite3.connect(path)) as con:
        return sorted(r[0] for r in con.execute("SELECT id FROM threads"))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


class ShareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, ".codex")
        self.home = os.path.join(self.tmp.name, ".codex-second")
        os.makedirs(self.root)
        os.makedirs(self.home)
        patcher = mock.patch.object(ca, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def share(self, item):
        msg = ca.share_item(self.home, item)
        src = os.path.join(self.home, item)
        return msg, src

    def test_missing_item_is_linked(self):
        msg, src = self.share("sessions")
        self.assertEqual(msg, "linked")
        self.assertEqual(os.readlink(src), os.path.join(self.root, "sessions"))

    def test_already_shared_is_left_alone(self):
        self.share("sessions")
        msg, _ = self.share("sessions")
        self.assertEqual(msg, "already shared")

    def test_sessions_dir_is_merged_and_duplicates_kept(self):
        write(os.path.join(self.root, "sessions/2026/a.jsonl"), "main-a")
        write(os.path.join(self.root, "sessions/2026/dup.jsonl"), "main-dup")
        write(os.path.join(self.home, "sessions/2026/b.jsonl"), "second-b")
        write(os.path.join(self.home, "sessions/2026/dup.jsonl"), "second-dup")

        msg, src = self.share("sessions")

        self.assertTrue(os.path.islink(src))
        self.assertEqual(read(os.path.join(self.root, "sessions/2026/b.jsonl")), "second-b")
        self.assertEqual(read(os.path.join(self.root, "sessions/2026/dup.jsonl")), "main-dup")
        aside = [d for d in os.listdir(self.home) if d.startswith("sessions.unmerged-")]
        self.assertEqual(len(aside), 1, msg)
        self.assertEqual(read(os.path.join(self.home, aside[0], "2026/dup.jsonl")),
                         "second-dup")

    def test_sessions_dir_moved_when_main_has_none(self):
        write(os.path.join(self.home, "sessions/x.jsonl"), "x")
        msg, src = self.share("sessions")
        self.assertEqual(msg, "moved to main home")
        self.assertEqual(read(os.path.join(src, "x.jsonl")), "x")

    def test_sqlite_rows_are_merged_without_overwriting(self):
        make_threads_db(os.path.join(self.root, "state_5.sqlite"), ["a", "b"])
        make_threads_db(os.path.join(self.home, "state_5.sqlite"), ["b", "c"])
        msg, src = self.share("state_5.sqlite")
        self.assertEqual(msg, "1 row(s) merged into main home")
        self.assertTrue(os.path.islink(src))
        self.assertEqual(thread_ids(src), ["a", "b", "c"])

    def test_sqlite_copied_with_wal_when_main_has_none(self):
        # Rows that only live in the -wal file (e.g. Codex crashed) must survive.
        live = os.path.join(self.tmp.name, "live.sqlite")
        src_db = os.path.join(self.home, "state_5.sqlite")
        with closing(sqlite3.connect(live)) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")
            con.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT)")
            con.executemany("INSERT INTO threads VALUES (?, ?)", [("a", "a"), ("b", "b")])
            con.commit()
            shutil.copy(live, src_db)
            shutil.copy(live + "-wal", src_db + "-wal")
        _, src = self.share("state_5.sqlite")
        self.assertEqual(thread_ids(os.path.join(self.root, "state_5.sqlite")), ["a", "b"])
        self.assertFalse(os.path.exists(src + "-wal"))

    def test_failed_sqlite_merge_leaves_source_untouched(self):
        write(os.path.join(self.root, "state_5.sqlite"), "not a database")
        make_threads_db(os.path.join(self.home, "state_5.sqlite"), ["a"])
        with redirect_stdout(StringIO()):
            msg, src = self.share("state_5.sqlite")
        self.assertEqual(msg, "could not merge, left separate")
        self.assertFalse(os.path.islink(src))
        self.assertEqual(thread_ids(src), ["a"])

    def test_session_index_lines_are_merged(self):
        write(os.path.join(self.root, "session_index.jsonl"), '{"id":"a"}\n{"id":"b"}\n')
        write(os.path.join(self.home, "session_index.jsonl"), '{"id":"b"}\n{"id":"c"}\n')
        msg, src = self.share("session_index.jsonl")
        self.assertEqual(msg, "1 line(s) merged into main home")
        self.assertEqual(read(src), '{"id":"a"}\n{"id":"b"}\n{"id":"c"}\n')


class HelperTest(unittest.TestCase):
    def test_pop_acct(self):
        reg = {"default": "main", "accounts": {}}
        self.assertEqual(ca.pop_acct(["--acct", "x", "-m", "o3"], reg), ("x", ["-m", "o3"]))
        self.assertEqual(ca.pop_acct(["-m", "o3"], reg), ("main", ["-m", "o3"]))
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", StringIO()):
            ca.pop_acct(["--acct"], reg)

    def test_plan_from_id_token(self):
        claims = {"https://api.openai.com/auth": {"chatgpt_plan_type": "pro"}}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        self.assertEqual(ca.plan_from_id_token(f"h.{payload}.s"), "pro")
        self.assertIsNone(ca.plan_from_id_token(""))
        self.assertIsNone(ca.plan_from_id_token("garbage"))

    def test_codex_processes(self):
        ps = (" 10 /usr/bin/codex app-server --listen unix://\n"
              " 11 node /home/u/.nvm/bin/codex resume\n"
              " 12 python3 /home/u/.local/bin/codex-acct share\n"
              " 13 vim codex.txt\n")
        with mock.patch.object(ca.subprocess, "run") as run:
            run.return_value.stdout = ps
            found = ca.codex_processes()
        self.assertEqual(found, ["/usr/bin/codex app-server --listen unix://",
                                 "node /home/u/.nvm/bin/codex resume"])

    def test_find_server_ignores_dead_pid(self):
        with tempfile.TemporaryDirectory() as d:
            tok = os.path.join(d, "token")
            write(tok, "secret\n")
            state = os.path.join(d, "state.json")
            write(state, json.dumps({"ws_url": "ws://x", "token_file": tok,
                                     "pid": os.getpid()}))
            with mock.patch.object(ca, "STATE", state), \
                    mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("CODEX_ACCT_WS", None)
                self.assertEqual(ca.find_server(), ("ws://x", "secret"))
                with mock.patch.object(ca, "pid_alive", return_value=False):
                    self.assertIsNone(ca.find_server())


if __name__ == "__main__":
    unittest.main()
