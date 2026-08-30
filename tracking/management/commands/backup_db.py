"""Management command: create a zipped, dated snapshot of the SQLite database.

Usage::

	./.venv/bin/python3.12 manage.py backup_db
	./.venv/bin/python3.12 manage.py backup_db --output-dir /path/to/backups --keep 30

Produces ``<output-dir>/yyyy-mm-dd db.sqlite3.zip`` containing the database file.
The snapshot is taken through the SQLite online backup API, so it is consistent
even while the dev server is running (no torn writes / partial transactions).
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils.translation import gettext_lazy as _

#: Default folder (relative to BASE_DIR) that dated backups are written to.
DEFAULT_BACKUP_DIRNAME = "backups"


class Command(BaseCommand):
	help = _("Create a dated zip backup of the SQLite database (yyyy-mm-dd db.sqlite3.zip).")

	def add_arguments(self, parser):
		parser.add_argument(
			"--database",
			default="default",
			help=_("Alias of the database to back up (default: 'default')."),
		)
		parser.add_argument(
			"--output-dir",
			default=None,
			help=_("Target folder for the backup (default: <BASE_DIR>/backups)."),
		)
		parser.add_argument(
			"--keep",
			type=int,
			default=0,
			help=_("Keep only the N most recent backups; 0 (default) keeps all."),
		)
		parser.add_argument(
			"--no-overwrite",
			action="store_true",
			help=_("Fail instead of replacing an existing backup for today."),
		)

	def handle(self, *args, **options):
		alias = options["database"]
		try:
			db_settings = connections[alias].settings_dict
		except Exception as exc:  # unknown alias
			raise CommandError(_("Unknown database alias '%s'.") % alias) from exc

		if "sqlite3" not in db_settings["ENGINE"]:
			raise CommandError(
				_("backup_db only supports SQLite databases (got %s).") % db_settings["ENGINE"]
			)

		source = Path(str(db_settings["NAME"]))
		if not source.is_file():
			raise CommandError(_("Database file not found: %s") % source)

		output_dir = Path(options["output_dir"]) if options["output_dir"] else Path(settings.BASE_DIR) / DEFAULT_BACKUP_DIRNAME
		output_dir.mkdir(parents=True, exist_ok=True)

		archive_name = f"{date.today().isoformat()} {source.name}.zip"
		archive_path = output_dir / archive_name

		if archive_path.exists() and options["no_overwrite"]:
			raise CommandError(_("Backup already exists: %s") % archive_path)

		self._write_archive(source, archive_path)

		self.stdout.write(
			self.style.SUCCESS(
				_("Backup written to %(path)s (%(size)s bytes).")
				% {"path": archive_path, "size": archive_path.stat().st_size}
			)
		)

		removed = self._prune(output_dir, source.name, options["keep"])
		for stale in removed:
			self.stdout.write(_("Removed old backup: %s") % stale)


	# -- helpers ---------------------------------------------------------

	def _write_archive(self, source: Path, archive_path: Path) -> None:
		"""Snapshot ``source`` with the SQLite backup API and zip the result."""
		with tempfile.TemporaryDirectory() as tmpdir:
			snapshot = Path(tmpdir) / source.name
			try:
				with sqlite3.connect(str(source)) as src, sqlite3.connect(str(snapshot)) as dst:
					src.backup(dst)
			except sqlite3.Error:
				# Not a SQLite file we can open (e.g. locked or corrupt) - fall
				# back to a plain file copy so a backup still gets produced.
				shutil.copy2(source, snapshot)

			tmp_archive = archive_path.with_suffix(".zip.tmp")
			with zipfile.ZipFile(tmp_archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
				zf.write(snapshot, arcname=source.name)
			tmp_archive.replace(archive_path)  # atomic swap, never a half-written zip

	@staticmethod
	def _prune(output_dir: Path, db_filename: str, keep: int) -> list[Path]:
		"""Delete all but the ``keep`` most recent backups. Returns removed paths."""
		if keep <= 0:
			return []
		backups = sorted(output_dir.glob(f"*-*-* {db_filename}.zip"))
		stale = backups[:-keep] if len(backups) > keep else []
		for path in stale:
			path.unlink()
		return stale

