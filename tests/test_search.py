from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from diagpl_optimize_core import search_products


class ProductSearchOrderTest(unittest.TestCase):
    def test_names_starting_with_query_come_before_substring_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "products.sqlite"
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE fetch_runs (id INTEGER PRIMARY KEY);
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
                    INSERT INTO fetch_runs(id) VALUES (1);
                    """
                )
                names = ["Choroba testowa", "Mikroglobulina", "OB", "Obraz krwi"]
                for product_id, name in enumerate(names, 1):
                    connection.execute(
                        "INSERT INTO products VALUES (?, ?, ?, ?, 'bloodtest')",
                        (product_id, name, f"slug-{product_id}", str(product_id)),
                    )
                    connection.execute(
                        "INSERT INTO product_offers VALUES (1, ?, 'available', 10, 'PLN', NULL, NULL, NULL, NULL)",
                        (product_id,),
                    )

            results = search_products(str(db), "OB")

        self.assertEqual([row["name"] for row in results], ["OB", "Obraz krwi", "Choroba testowa", "Mikroglobulina"])


if __name__ == "__main__":
    unittest.main()
