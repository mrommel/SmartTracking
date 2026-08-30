"""Tests for the ``backup_db`` management command."""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test import TestCase


class BackupDbCommandTests(TestCase):
	"""The command writes a dated zip archive containing the database file."""

	def setUp(self):
		self._tmp = tempfile.TemporaryDirectory()
		self.tmpdir = Path(self._tmp.name)
		self.addCleanup(self._tmp.cleanup)

		self.db_path = self.tmpdir / "db.sqlite3"
		with sqlite3.connect(self.db_path) as con:
			con.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT)")
			con.execute("INSERT INTO demo (name) VALUES ('smt')")

		self.out_dir = self.tmpdir / "backups"

	def _run(self, engine="django.db.backends.sqlite3", name=None, **kwargs):
		out = StringIO()
		overrides = {"ENGINE": engine, "NAME": name if name is not None else str(self.db_path)}
		# `override_settings(DATABASES=...)` does not reach an already-opened
		# connection, so patch the live connection's settings_dict instead.
		with patch.dict(connections["default"].settings_dict, overrides):
			call_command("backup_db", output_dir=str(self.out_dir), stdout=out, **kwargs)
		return out.getvalue()

	def test_creates_dated_archive(self):
		self._run()
		expected = self.out_dir / f"{date.today().isoformat()} db.sqlite3.zip"
		self.assertTrue(expected.is_file(), f"missing backup: {expected}")

	def test_archive_contains_readable_database(self):
		self._run()
		archive = self.out_dir / f"{date.today().isoformat()} db.sqlite3.zip"
		with zipfile.ZipFile(archive) as zf:
			self.assertEqual(zf.namelist(), ["db.sqlite3"])
			zf.extractall(self.tmpdir / "restored")

		with sqlite3.connect(self.tmpdir / "restored" / "db.sqlite3") as con:
			self.assertEqual(con.execute("SELECT name FROM demo").fetchone()[0], "smt")

	def test_no_overwrite_raises_when_backup_exists(self):
		self._run()
		with self.assertRaises(CommandError):
			self._run(no_overwrite=True)

	def test_overwrites_same_day_backup_by_default(self):
		self._run()
		self._run()  # must not raise
		self.assertEqual(len(list(self.out_dir.glob("*.zip"))), 1)

	def test_keep_prunes_older_backups(self):
		self._run()
		for stamp in ("2020-01-01", "2020-01-02"):
			(self.out_dir / f"{stamp} db.sqlite3.zip").write_bytes(b"old")

		self._run(keep=2)
		remaining = sorted(p.name for p in self.out_dir.glob("*.zip"))
		self.assertEqual(len(remaining), 2)
		self.assertNotIn("2020-01-01 db.sqlite3.zip", remaining)

	def test_missing_database_file_raises(self):
		self.db_path.unlink()
		with self.assertRaises(CommandError):
			self._run()

	def test_non_sqlite_engine_raises(self):
		with self.assertRaises(CommandError):
			self._run(engine="django.db.backends.postgresql", name="smt")

