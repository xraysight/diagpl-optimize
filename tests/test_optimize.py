from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from diagpl_optimize_core import create_schema, insert_snapshot, optimize_products, replace_institutions


class OptionalSolverTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = str(Path(directory.name) / "products.sqlite")
        self.names = [f"Badanie {i}" for i in range(1, 22)]
        products = [
            {
                "id": i, "uuid": str(i), "slug": f"badanie-{i}", "name": name,
                "type": "bloodtest", "elabCode": str(i),
                "prices": {"sellState": "available", "sale": {"gross": 10, "currency": "PLN"}},
            }
            for i, name in enumerate(self.names, 1)
        ]
        with closing(sqlite3.connect(self.db)) as connection, connection:
            create_schema(connection)
            replace_institutions(connection, {"data": [{"id": 889, "name": "Punkt testowy"}]})
            insert_snapshot(connection, {"source": "test", "pages": [], "data": products}, 889, 21)
        self.numpy = ModuleType("numpy")
        self.numpy.__spec__ = ModuleSpec("numpy", loader=None)

    def test_large_auto_request_returns_approximate_result_with_install_help_if_scipy_is_missing(self) -> None:
        with patch.dict(sys.modules, {"numpy": self.numpy, "scipy": None}):
            result = optimize_products(self.db, self.names)

        self.assertEqual(result["solver"], "greedy")
        self.assertEqual(result["optimized_sum"], 210)
        self.assertIn("wynik jest przybliżony", result["warning"].lower())
        self.assertIn("-m pip install --upgrade numpy scipy", result["warning"])

    def test_explicit_ilp_failure_gives_a_powershell_command_for_the_running_python(self) -> None:
        with (
            patch.dict(sys.modules, {"numpy": self.numpy, "scipy": None}),
            patch.object(sys, "platform", "win32"),
            patch.object(sys, "executable", r"C:\Piotr's Apps\.venv\Scripts\python.exe"),
        ):
            with self.assertRaises(RuntimeError) as caught:
                optimize_products(self.db, self.names, solver="ilp")

        self.assertIn("PowerShell", str(caught.exception))
        self.assertIn(r"& 'C:\Piotr''s Apps\.venv\Scripts\python.exe' -m pip install --upgrade numpy scipy",
                      str(caught.exception).splitlines())


class OptimizationLinksTest(unittest.TestCase):
    def test_chosen_packages_and_products_include_slugs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "products.sqlite"
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE fetch_runs (id INTEGER PRIMARY KEY, institution_id INTEGER NOT NULL);
                    CREATE TABLE products (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        slug TEXT NOT NULL,
                        elab_code TEXT NOT NULL,
                        type TEXT NOT NULL
                    );
                    CREATE TABLE product_offers (
                        fetch_run_id INTEGER NOT NULL,
                        product_id INTEGER NOT NULL,
                        sell_state TEXT NOT NULL,
                        sale_gross REAL,
                        sale_currency TEXT,
                        regular_gross REAL,
                        regular_currency TEXT,
                        minimal_gross REAL,
                        minimal_currency TEXT
                    );
                    CREATE TABLE package_items (
                        package_id INTEGER NOT NULL,
                        child_product_id INTEGER NOT NULL,
                        position INTEGER NOT NULL
                    );
                    INSERT INTO fetch_runs VALUES (1, 889);
                    INSERT INTO products VALUES
                        (1, 'Badanie A', 'badanie-a', 'A', 'bloodtest'),
                        (2, 'Badanie B', 'badanie-b', 'B', 'bloodtest'),
                        (3, 'Badanie C', 'badanie-c', 'C', 'bloodtest'),
                        (10, 'Pakiet A+B', 'pakiet-a-b', 'P', 'package');
                    INSERT INTO product_offers VALUES
                        (1, 1, 'available', 10, 'PLN', NULL, NULL, NULL, NULL),
                        (1, 2, 'available', 10, 'PLN', NULL, NULL, NULL, NULL),
                        (1, 3, 'available', 10, 'PLN', NULL, NULL, NULL, NULL),
                        (1, 10, 'available', 10, 'PLN', NULL, NULL, NULL, NULL);
                    INSERT INTO package_items VALUES (10, 1, 0), (10, 2, 1);
                    """
                )

            result = optimize_products(str(db), ["Badanie A", "Badanie B", "Badanie C"], institution_id=889)

        chosen = {(item["kind"], item["name"]): item.get("slug") for item in result["chosen"]}
        self.assertEqual(chosen[("package", "Pakiet A+B")], "pakiet-a-b")
        self.assertEqual(chosen[("product", "Badanie C")], "badanie-c")


if __name__ == "__main__":
    unittest.main()
