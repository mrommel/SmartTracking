#!/usr/bin/env python3
"""CI translation guard: fail if any msgid is untranslated or catalogs are stale.

Usage:
    python scripts/check_translations.py [LANGUAGES...]

  LANGUAGES  Languages to check (e.g. de). Defaults to all non-default
             languages in settings.LANGUAGES. Pass --all to check every
             locale including the default language.

Exit codes:
    0  All catalogs are complete and .mo files are up to date.
    1  One or more untranslated strings or stale catalogs found.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from subprocess import PIPE, run, CalledProcessError

# ---------------------------------------------------------------------------
# Configuration (mirrors setup/settings.py so this script is independent)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR / "setup"
LOCALE_DIR = BASE_DIR / "tracking" / "locale"
# Must match the DJANGO_SETTINGS_MODULE default in manage.py (the
# ``setup.settings`` package itself does not define settings).
SETTINGS_MODULE = "setup.settings.dev"
LANGUAGE_CODE = "en-us"
LANGUAGES = [
    ("de", "German"),
    ("en", "English"),
]

# Strings that are OK to be untranslated (fuzzy/obsolete/template keys)
IGNORE_MSGIDS = frozenset((
    "",  # empty msgid (directory header)
))


def ensure_po_files_exist() -> None:
    """Run ``makemessages`` to regenerate .po catalogs before checking."""
    result = run(
        (
            sys.executable,
            str(BASE_DIR / "manage.py"),
            "makemessages",
            "-l", "de",
            "-l", "en",
            "-e", "html,txt,py",
            "--ignore", ".venv/*",
            "--ignore", "htmlcov/*",
            "--ignore", ".pytest_cache/*",
        ),
        cwd=BASE_DIR,
        stdout=PIPE, stderr=PIPE, text=True,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": SETTINGS_MODULE},
    )
    if result.returncode != 0:
        print(f"FATAL: makemessages failed (exit {result.returncode})")
        if result.stderr:
            print(result.stderr.strip())
        sys.exit(1)


def ensure_mo_files() -> bool:
    """Compile .po → .mo; return False if anything failed."""
    result = run(
        (
            sys.executable,
            str(BASE_DIR / "manage.py"),
            "compilemessages",
            "--ignore=.venv/*",
        ),
        cwd=BASE_DIR,
        stdout=PIPE, stderr=PIPE, text=True,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": SETTINGS_MODULE},
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# polib — the .po parser (lightweight, no Django dependency)
# ---------------------------------------------------------------------------
def _try_import_polib():
    try:
        import polib  # noqa: F401
        return polib
    except ImportError:
        print(
            "ERROR: polib is not installed.\n"
            "Install it with: pip install polib\n"
            "Or add it to requirements.txt.",
            file=sys.stderr,
        )
        sys.exit(1)


polib = _try_import_polib()


def check_po_file(locale: str, polib) -> list[str]:
    """Return a list of untranslated msgid strings for *locale*."""
    po_path = LOCALE_DIR / locale / "LC_MESSAGES" / "django.po"
    if not po_path.exists():
        return [f"  MISSING: {po_path} (file does not exist)"]

    po = polib.pofile(str(po_path))
    untranslated: list[str] = []
    for entry in po:
        # Skip empty msgids (PO file header) and fuzzy/obsolete entries
        if entry.msgid in IGNORE_MSGIDS:
            continue
        if entry.obsolete or entry.fuzzy:
            continue
        # An entry is untranslated when msgstr is empty (or only whitespace)
        msgstr = getattr(entry, "msgstr", "") or ""
        if not msgstr.strip():
            untranslated.append(f"  \"{entry.msgid}\" (line {entry.linenum})")
    return untranslated


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    all_langs = [code for code, _ in LANGUAGES]
    args = sys.argv[1:]

    if "--all" in args:
        langs = all_langs
    else:
        # Check every language except the default LANGUAGE_CODE
        langs = [code for code, _ in LANGUAGES if code != LANGUAGE_CODE.split("-")[0]
                 and code != LANGUAGE_CODE]
        if not langs:
            # Fallback: if LANGUAGE_CODE doesn't match, check all non-default
            langs = all_langs[1:] if len(all_langs) > 1 else all_langs

    # Allow explicit language list
    if args and not args[0].startswith("--"):
        langs = args

    if not langs:
        print("No languages to check. Pass --all or a language code (e.g. de).")
        sys.exit(0)

    # Phase 1: generate fresh catalogs
    print("=== Generating translation catalogs ===")
    ensure_po_files_exist()

    # Phase 2: check for untranslated strings
    print("=== Checking for untranslated strings ===")
    all_untranslated: dict[str, list[str]] = {}
    for locale in langs:
        untranslated = check_po_file(locale, polib)
        if untranslated:
            all_untranslated[locale] = untranslated
            print(f"\n{locale}: {len(untranslated)} untranslated msgid(s)")
            for line in untranslated:
                print(line)

    # Phase 3: compile and check for stale catalogs
    print("\n=== Compiling catalogs ===")
    mo_ok = ensure_mo_files()
    if not mo_ok:
        print("ERROR: compilemessages failed — catalogs may be stale or corrupt.")
    else:
        print("OK — all .mo files compiled successfully.")

    # Summary
    errors: list[str] = []
    if all_untranslated:
        total = sum(len(v) for v in all_untranslated.values())
        errors.append(
            f"FAIL: {total} untranslated msgid(s) across "
            f"{len(all_untranslated)} language(s). All msgids must have a msgstr."
        )
    if not mo_ok:
        errors.append("FAIL: compilemessages reported errors.")

    if errors:
        for e in errors:
            print(f"\n>>> {e}")
        sys.exit(1)

    print("\n=== All translation checks passed ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
