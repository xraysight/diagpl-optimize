from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
from contextlib import closing
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote
from urllib.request import Request, urlopen

from diagpl_optimize_core import create_schema, replace_institutions


GUI_PATH = Path(__file__).resolve().parents[1] / "diagpl-optimize-gui.py"
SPEC = importlib.util.spec_from_file_location("diagpl_optimize_gui", GUI_PATH)
assert SPEC and SPEC.loader
GUI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUI)


class GuiInstitutionApiTest(unittest.TestCase):
    def test_gui_command_line_help_is_polish(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GUI_PATH), "--pomoc"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("użycie:", result.stdout)
        self.assertIn("opcje:", result.stdout)
        self.assertIn("--adres", result.stdout)
        self.assertIn("--port", result.stdout)
        self.assertIn("--baza", result.stdout)
        self.assertIn("--bez-przegladarki", result.stdout)
        self.assertNotIn("--host", result.stdout)
        self.assertNotIn("--db", result.stdout)
        self.assertNotIn("--no-browser", result.stdout)

    def test_page_requires_institution_before_product_search(self) -> None:
        self.assertIn('id="institution-search"', GUI.HTML)
        self.assertIn('id="institution-matches"', GUI.HTML)
        self.assertIn('id="search" disabled', GUI.HTML)
        self.assertIn("/api/institution", GUI.HTML)

    def test_institution_ids_are_hidden_and_product_area_is_locked_during_download(self) -> None:
        self.assertNotIn("ID ${institution.id}", GUI.HTML)
        self.assertNotIn("'ID '+institution.id", GUI.HTML)
        self.assertIn("setProductAreaBusy(true)", GUI.HTML)
        self.assertIn("setProductAreaBusy(false)", GUI.HTML)

    def test_selected_products_are_persisted_per_institution_and_can_be_cleared(self) -> None:
        self.assertIn('id="clear-selected"', GUI.HTML)
        self.assertIn("localStorage.setItem", GUI.HTML)
        self.assertIn("institutionId:selectedInstitution.id", GUI.HTML)
        self.assertIn("restoreProductSelection()", GUI.HTML)

    def test_prepare_database_initializes_it_when_needed(self) -> None:
        with patch.object(GUI, "initialize_database_if_needed", return_value={"initialized": True}) as initialize:
            result = GUI.prepare_database("new.sqlite")
        initialize.assert_called_once_with("new.sqlite")
        self.assertTrue(result["initialized"])

    def test_selecting_institution_refreshes_products_for_its_id(self) -> None:
        db = Path(self.id().replace(".", "-") + ".sqlite").resolve()
        status = {
            "fetched_at": "2026-01-01",
            "total_items": 10,
            "institutions": 1,
            "selected_institution": {"id": 889, "name": "Punkt Gdańsk", "full_address": "Gdańsk"},
        }
        try:
            with closing(sqlite3.connect(db)) as connection, connection:
                create_schema(connection)
                replace_institutions(connection, {"data": [{"id": 889, "name": "Punkt Gdańsk"}]})
            GUI.Handler.db = str(db)
            server = ThreadingHTTPServer(("127.0.0.1", 0), GUI.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            request = Request(
                f"http://127.0.0.1:{server.server_port}/api/institution",
                data=json.dumps({"institution_id": 889}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with (
                    patch.object(GUI, "refresh_database", return_value={"items": 10}) as refresh,
                    patch.object(GUI, "database_status", return_value=status),
                    urlopen(request, timeout=5) as response,
                ):
                    payload = json.load(response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            db.unlink(missing_ok=True)
        refresh.assert_called_once_with(str(db), 889)
        self.assertEqual(payload["status"]["selected_institution"]["id"], 889)

    def test_institution_search_endpoint_returns_local_matches(self) -> None:
        db = Path(self.id().replace(".", "-") + ".sqlite").resolve()
        try:
            with closing(sqlite3.connect(db)) as connection, connection:
                create_schema(connection)
                replace_institutions(
                    connection,
                    {
                        "data": [
                            {"id": 889, "name": "Punkt Gdańsk", "address": {"fullAddress": "Gdańsk, Zwycięstwa 31"}},
                            {"id": 7, "name": "Punkt Łódź", "address": {"fullAddress": "Łódź, Testowa 1"}},
                        ]
                    },
                )
            GUI.Handler.db = str(db)
            server = ThreadingHTTPServer(("127.0.0.1", 0), GUI.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/institutions?q={quote('GDAŃSK')}", timeout=5) as response:
                    payload = json.load(response)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        finally:
            db.unlink(missing_ok=True)
        self.assertEqual(payload, [{"id": 889, "name": "Punkt Gdańsk", "full_address": "Gdańsk, Zwycięstwa 31", "city_name": None}])


if __name__ == "__main__":
    unittest.main()
