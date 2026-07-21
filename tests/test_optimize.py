from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from diagpl_optimize_core import optimize_products


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
