from __future__ import annotations

import subprocess
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "diagpl-optimize-cli.py"


class CliHelpTest(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_no_arguments_matches_polish_help_flag(self) -> None:
        no_args = self.run_cli()
        help_flag = self.run_cli("--pomoc")

        self.assertEqual(no_args.returncode, 0)
        self.assertEqual(no_args.stdout, help_flag.stdout)
        self.assertEqual(no_args.stderr, help_flag.stderr)

    def test_main_help_is_entirely_polish(self) -> None:
        result = self.run_cli("--pomoc")
        self.assertEqual(result.returncode, 0)
        for command in (
            "inicjalizuj",
            "pobierz",
            "lista-punktow",
            "lista-badan",
            "lista-pakietow",
            "pakiet",
            "optymalizuj",
        ):
            self.assertIn(command, result.stdout)
        self.assertIn("użycie:", result.stdout)
        self.assertIn("opcje:", result.stdout)
        self.assertIn("komendy:", result.stdout)
        self.assertIn("nie jest poprawnie zainicjalizowana", result.stdout)
        self.assertNotIn("usage:", result.stdout)
        self.assertNotIn("options:", result.stdout)
        self.assertNotIn("--help", result.stdout)

    def test_optimize_does_not_accept_point_option(self) -> None:
        help_result = self.run_cli("optymalizuj", "--pomoc")
        invalid_result = self.run_cli("optymalizuj", "--punkt", "889", "OB")
        self.assertEqual(help_result.returncode, 0)
        self.assertNotIn("--punkt", help_result.stdout)
        self.assertEqual(invalid_result.returncode, 2)
        self.assertIn("nierozpoznane argumenty", invalid_result.stderr)

    def test_fetch_requires_point(self) -> None:
        result = self.run_cli("pobierz")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--punkt", result.stderr)
        self.assertIn("wymagane", result.stderr)

    def test_optimize_help_translates_options_and_algorithm_values(self) -> None:
        result = self.run_cli("optymalizuj", "--pomoc")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--algorytm", result.stdout)
        self.assertIn("--maks-dokladnych-badan", result.stdout)
        self.assertIn("automatyczny", result.stdout)
        self.assertIn("dokladny", result.stdout)
        self.assertIn("zachlanny", result.stdout)
        self.assertNotIn("--solver", result.stdout)
        self.assertNotIn("--max-exact-products", result.stdout)

    def test_english_command_and_option_are_rejected(self) -> None:
        old_command = self.run_cli("fetch")
        old_option = self.run_cli("pobierz", "--institution", "889")
        self.assertEqual(old_command.returncode, 2)
        self.assertEqual(old_option.returncode, 2)
        self.assertIn("nieprawidłowa komenda", old_command.stderr)
        self.assertIn("--punkt", old_option.stderr)

    def test_list_institutions_prints_id_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "institutions.sqlite"
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute("CREATE TABLE institutions(id INTEGER PRIMARY KEY, name TEXT, full_address TEXT)")
                connection.executemany(
                    "INSERT INTO institutions VALUES (?, ?, ?)",
                    [(12, "Punkt B", "Adres B"), (3, "Punkt A", "Adres A")],
                )
            result = self.run_cli("lista-punktow", "--baza", str(db))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["3\tPunkt A\tAdres A", "12\tPunkt B\tAdres B"])

    def test_list_institutions_filters_by_arbitrary_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "institutions.sqlite"
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute("CREATE TABLE institutions(id INTEGER PRIMARY KEY, name TEXT, full_address TEXT)")
                connection.executemany(
                    "INSERT INTO institutions VALUES (?, ?, ?)",
                    [(12, "Punkt B", "Łódź, Adres B"), (3, "Punkt A", "Gdańsk, Adres A")],
                )
            result = self.run_cli("lista-punktow", "--baza", str(db), "--szukaj", "ŁÓDŹ")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["12\tPunkt B\tŁódź, Adres B"])

    def test_uninitialized_database_errors_point_to_init(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "missing.sqlite"
            listed = self.run_cli("lista-punktow", "--baza", str(db))
            fetched = self.run_cli(
                "pobierz", "--baza", str(db), "--punkt", "889", "--adres-api", "http://127.0.0.1:1"
            )
        self.assertEqual(listed.returncode, 1)
        self.assertEqual(fetched.returncode, 1)
        self.assertIn("inicjalizuj", listed.stderr.lower())
        self.assertIn("inicjalizuj", fetched.stderr.lower())


if __name__ == "__main__":
    unittest.main()
