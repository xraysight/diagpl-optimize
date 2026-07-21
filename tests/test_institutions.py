from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import diagpl_optimize_core as core

from diagpl_optimize_core import (
    DEFAULT_INSTITUTIONS_URL,
    create_schema,
    database_status,
    fetch_all_institutions,
    refresh_database,
    replace_institutions,
)


class InstitutionRefreshTest(unittest.TestCase):
    def test_search_institutions_matches_unicode_text_in_name_or_address(self) -> None:
        snapshot = {
            "source": DEFAULT_INSTITUTIONS_URL,
            "pages": [],
            "data": [
                {"id": 2, "name": "Punkt Łódź Widzew", "temporaryDisabled": False, "address": {"fullAddress": "ul. Druga 2"}},
                {"id": 1, "name": "Punkt Centralny", "temporaryDisabled": False, "address": {"fullAddress": "Łódź, ul. Pierwsza 1"}},
                {"id": 3, "name": "Punkt Gdańsk", "temporaryDisabled": False, "address": {"fullAddress": "ul. Trzecia 3"}},
            ],
            "meta": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "institutions.sqlite"
            with closing(sqlite3.connect(db)) as connection, connection:
                create_schema(connection)
                replace_institutions(connection, snapshot)
            results = core.search_institutions(str(db), "ŁÓDŹ")
        self.assertEqual([row["id"] for row in results], [2, 1])
        self.assertEqual(results[0]["full_address"], "ul. Druga 2")

    def test_initialize_database_if_needed_only_downloads_for_new_database(self) -> None:
        snapshot = {
            "source": DEFAULT_INSTITUTIONS_URL,
            "pages": [{"meta": {"current_page": 1, "last_page": 1}}],
            "data": [{"id": 7, "name": "Punkt startowy", "temporaryDisabled": False}],
            "meta": {"current_page": 1, "last_page": 1},
        }
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "gui.sqlite"
            with patch.object(core, "fetch_all_institutions", return_value=snapshot) as fetch:
                first = core.initialize_database_if_needed(str(db), timeout=1, sleep_seconds=0)
            with patch.object(core, "fetch_all_institutions", side_effect=AssertionError("unexpected download")):
                second = core.initialize_database_if_needed(str(db), timeout=1, sleep_seconds=0)
        self.assertTrue(first["initialized"])
        self.assertFalse(second["initialized"])
        fetch.assert_called_once()

    def test_init_creates_database_with_institutions_only(self) -> None:
        snapshot = {
            "source": DEFAULT_INSTITUTIONS_URL,
            "pages": [{"meta": {"current_page": 1, "last_page": 1}}],
            "data": [{"id": 7, "name": "Punkt startowy", "temporaryDisabled": False}],
            "meta": {"current_page": 1, "last_page": 1},
        }
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "initialized.sqlite"
            output = StringIO()
            with patch.object(core, "fetch_all_institutions", return_value=snapshot), redirect_stdout(output):
                result = core.run_init(Namespace(db=str(db), timeout=1, sleep=0.0))
            with closing(sqlite3.connect(db)) as connection, connection:
                institutions = connection.execute("SELECT id, name FROM institutions").fetchall()
                products = connection.execute("SELECT count(*) FROM products").fetchone()[0]
        self.assertEqual(result, 0)
        self.assertEqual(institutions, [(7, "Punkt startowy")])
        self.assertEqual(products, 0)
        self.assertIn('"institutions": 1', output.getvalue())

    def test_database_status_includes_institution_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "products.sqlite"
            with closing(sqlite3.connect(db)) as connection, connection:
                create_schema(connection)
                connection.execute(
                    "INSERT INTO fetch_runs(source_url,institution_id,limit_per_page,page_count,total_items,fetched_at) VALUES ('test',1,200,1,12,'2026-01-01')"
                )
                connection.execute(
                    "INSERT INTO institutions(id,name,full_address,temporary_disabled,raw_json,updated_at) VALUES (1,'Punkt','Adres 1',0,'{}','2026-01-01')"
                )
            self.assertEqual(
                database_status(str(db)),
                {
                    "fetched_at": "2026-01-01",
                    "total_items": 12,
                    "institutions": 1,
                    "selected_institution": {"id": 1, "name": "Punkt", "full_address": "Adres 1"},
                },
            )

    def test_refresh_does_not_write_when_institution_download_fails(self) -> None:
        product_snapshot = {"source": "products", "pages": [], "data": []}
        with (
            patch("diagpl_optimize_core.fetch_all_pages", return_value=product_snapshot) as fetch_products,
            patch("diagpl_optimize_core.fetch_all_institutions", side_effect=RuntimeError("network error")),
            patch("diagpl_optimize_core.write_fresh_database") as write_database,
        ):
            with self.assertRaisesRegex(RuntimeError, "network error"):
                refresh_database("unused.sqlite", 321)
        self.assertEqual(fetch_products.call_args.args[1], 321)
        write_database.assert_not_called()

    def test_fetches_every_page_with_required_filters(self) -> None:
        seen_urls: list[str] = []

        def fake_fetch(url: str, timeout: int) -> dict:
            seen_urls.append(url)
            page = int(parse_qs(urlparse(url).query)["page"][0])
            return {
                "data": [{"id": page, "name": f"Punkt {page}", "slug": f"punkt-{page}"}],
                "meta": {"current_page": page, "last_page": 2, "total": 2},
            }

        with patch("diagpl_optimize_core.fetch_json_url", side_effect=fake_fetch):
            snapshot = fetch_all_institutions(DEFAULT_INSTITUTIONS_URL, 200, timeout=5, sleep_seconds=0)

        self.assertEqual([item["id"] for item in snapshot["data"]], [1, 2])
        self.assertEqual(len(seen_urls), 2)
        query = parse_qs(urlparse(seen_urls[0]).query)
        self.assertEqual(query["include"], ["address,city"])
        self.assertEqual(query["filter[attributes]"], ["ESHOP,ECO"])
        self.assertEqual(query["filter[temporaryDisabled]"], ["false"])
        self.assertEqual(query["limit"], ["200"])

    def test_replaces_the_current_institution_list(self) -> None:
        first = {
            "fetched_at": "2026-01-01T00:00:00+00:00",
            "data": [
                {
                    "id": 889,
                    "externalUuid": "uuid-889",
                    "databaseId": 19,
                    "localId": 123,
                    "testPriceId": 456,
                    "temporaryDisabled": False,
                    "slug": "warszawa",
                    "name": "Punkt Warszawa",
                    "address": {
                        "id": 889,
                        "fullAddress": "Warszawa, Testowa 1",
                        "street": "Testowa",
                        "streetType": "ul.",
                        "number": "1",
                        "postalCode": "00-001",
                        "addressInfo": None,
                        "city": {"id": 1, "name": "Warszawa", "slug": "warszawa"},
                    },
                },
                {"id": 900, "slug": "stary-punkt", "name": "Stary punkt"},
            ],
        }
        second = {"fetched_at": "2026-01-02T00:00:00+00:00", "data": [first["data"][0]]}

        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "products.sqlite"
            with closing(sqlite3.connect(db)) as connection, connection:
                create_schema(connection)
                replace_institutions(connection, first)
                replace_institutions(connection, second)
                rows = connection.execute(
                    "SELECT id, external_uuid, database_id, local_id, test_price_id, name, full_address, city_name, updated_at FROM institutions"
                ).fetchall()

        self.assertEqual(
            rows,
            [(889, "uuid-889", 19, 123, 456, "Punkt Warszawa", "Warszawa, Testowa 1", "Warszawa", second["fetched_at"])],
        )


if __name__ == "__main__":
    unittest.main()
