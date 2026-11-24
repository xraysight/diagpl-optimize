#!/usr/bin/env python3
"""Pobieranie katalogu DIAG.pl do SQLite i optymalizacja kosztu badań.

Przykłady użycia:
  python3 diagpl-optimize-cli.py inicjalizuj
  python3 diagpl-optimize-cli.py pobierz --punkt 889
  python3 diagpl-optimize-cli.py lista-badan
  python3 diagpl-optimize-cli.py lista-pakietow
  python3 diagpl-optimize-cli.py pakiet "Badania na nerki"
  python3 diagpl-optimize-cli.py optymalizuj "CRP, ilościowo" "Morfologia krwi"
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_BASE_URL = "https://api-eshop.diag.pl/api/front/v1/products"
DEFAULT_INSTITUTIONS_URL = "https://api-eshop.diag.pl/api/v1/institution-service/institutions/search"
DEFAULT_INSTITUTION_ID = 889
DEFAULT_LIMIT = 200
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = str(SCRIPT_DIR / "diagpl-products.sqlite")
USER_AGENT = "diagpl-optimize/1.0 (+Hermes Agent)"


class PolishArgumentParser(argparse.ArgumentParser):
    """ArgumentParser z polską pomocą i komunikatami błędów."""

    def __init__(self, *args: object, **kwargs: Any) -> None:
        add_help = bool(kwargs.pop("add_help", True))
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = "argumenty pozycyjne"
        self._optionals.title = "opcje"
        if add_help:
            self.add_argument("-h", "--pomoc", action="help", help="wyświetl tę pomoc i zakończ")

    @staticmethod
    def _translate(text: str) -> str:
        replacements = (
            ("usage:", "użycie:"),
            ("argument KOMENDA: invalid choice:", "argument KOMENDA: nieprawidłowa komenda:"),
            ("argument komenda: invalid choice:", "argument komenda: nieprawidłowa komenda:"),
            ("invalid choice:", "nieprawidłowa wartość:"),
            ("(choose from ", "(wybierz spośród "),
            ("the following arguments are required:", "wymagane są następujące argumenty:"),
            ("unrecognized arguments:", "nierozpoznane argumenty:"),
            ("expected one argument", "oczekiwano jednej wartości"),
            ("invalid int value:", "nieprawidłowa liczba całkowita:"),
            ("invalid float value:", "nieprawidłowa liczba:"),
        )
        for source, target in replacements:
            text = text.replace(source, target)
        return text

    def format_usage(self) -> str:
        return self._translate(super().format_usage())

    def format_help(self) -> str:
        return self._translate(super().format_help())

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: błąd: {self._translate(message)}\n")


POLISH_SOLVERS = {
    "automatyczny": "auto",
    "dokladny": "exact",
    "ilp": "ilp",
    "zachlanny": "greedy",
}

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS fetch_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_url TEXT NOT NULL,
  institution_id INTEGER NOT NULL,
  limit_per_page INTEGER NOT NULL,
  page_count INTEGER NOT NULL,
  total_items INTEGER NOT NULL,
  fetched_at TEXT NOT NULL,
  raw_meta_json TEXT
);

CREATE TABLE IF NOT EXISTS institutions (
  id INTEGER PRIMARY KEY,
  external_uuid TEXT,
  database_id INTEGER,
  local_id INTEGER,
  test_price_id INTEGER,
  slug TEXT,
  name TEXT NOT NULL,
  temporary_disabled INTEGER NOT NULL CHECK (temporary_disabled IN (0,1)),
  address_id INTEGER,
  full_address TEXT,
  street TEXT,
  street_type TEXT,
  street_number TEXT,
  postal_code TEXT,
  address_info TEXT,
  city_id INTEGER,
  city_name TEXT,
  city_slug TEXT,
  raw_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS media (
  uuid TEXT PRIMARY KEY,
  file_name TEXT,
  mime_type TEXT,
  media_type TEXT,
  path TEXT,
  url TEXT,
  size INTEGER,
  name TEXT,
  description TEXT,
  created_at TEXT,
  alt TEXT,
  width INTEGER,
  height INTEGER
);

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY,
  uuid TEXT NOT NULL UNIQUE,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('bloodtest', 'package')),
  elab_code TEXT NOT NULL UNIQUE,
  icd_code TEXT,
  global_waiting_time TEXT,
  thumbnail_media_uuid TEXT REFERENCES media(uuid),
  thumbnail_background_color TEXT,
  additional_info_content TEXT,
  additional_info_url TEXT,
  additional_info_copy_value TEXT,
  raw_product_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_offers (
  fetch_run_id INTEGER NOT NULL REFERENCES fetch_runs(id) ON DELETE CASCADE,
  institution_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,

  is_ecommerce INTEGER NOT NULL CHECK (is_ecommerce IN (0,1)),
  requires_material_collection_fee INTEGER NOT NULL CHECK (requires_material_collection_fee IN (0,1)),
  has_consultation INTEGER NOT NULL CHECK (has_consultation IN (0,1)),
  is_shipping INTEGER NOT NULL CHECK (is_shipping IN (0,1)),
  has_block_home_material_collection INTEGER NOT NULL CHECK (has_block_home_material_collection IN (0,1)),
  has_free_labplus_consultation INTEGER NOT NULL CHECK (has_free_labplus_consultation IN (0,1)),
  has_local_price INTEGER NOT NULL CHECK (has_local_price IN (0,1)),

  sale_gross REAL,
  sale_currency TEXT,
  regular_gross REAL,
  regular_currency TEXT,
  minimal_gross REAL,
  minimal_currency TEXT,
  lowest_gross REAL,
  lowest_currency TEXT,
  vat_rate TEXT,
  waiting_time TEXT,
  regular_price_message TEXT,
  regular_price_tooltip TEXT,
  sell_state TEXT NOT NULL,

  raw_prices_json TEXT NOT NULL,
  PRIMARY KEY (fetch_run_id, product_id)
);

CREATE TABLE IF NOT EXISTS institution_attributes (
  code TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS product_institution_attributes (
  fetch_run_id INTEGER NOT NULL REFERENCES fetch_runs(id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  attribute_code TEXT NOT NULL REFERENCES institution_attributes(code),
  PRIMARY KEY (fetch_run_id, product_id, attribute_code)
);

CREATE TABLE IF NOT EXISTS package_items (
  package_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  child_product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  child_status TEXT NOT NULL,
  PRIMARY KEY (package_id, child_product_id),
  UNIQUE (package_id, position)
);

CREATE INDEX IF NOT EXISTS idx_products_type ON products(type);
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_institutions_city_name ON institutions(city_name);
CREATE INDEX IF NOT EXISTS idx_institutions_name ON institutions(name);
CREATE INDEX IF NOT EXISTS idx_offers_institution_sell_state ON product_offers(institution_id, sell_state);
CREATE INDEX IF NOT EXISTS idx_offers_prices ON product_offers(sale_gross, regular_gross, minimal_gross);
CREATE INDEX IF NOT EXISTS idx_package_items_child ON package_items(child_product_id);
"""

TABLES_TO_CLEAR = [
    "package_items",
    "product_institution_attributes",
    "institution_attributes",
    "product_offers",
    "products",
    "media",
    "institutions",
    "fetch_runs",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def money(prices: dict[str, Any], key: str) -> tuple[float | None, str | None]:
    value = prices.get(key)
    if isinstance(value, dict):
        return value.get("gross"), value.get("currency")
    return None, None


def build_url(base_url: str, institution_id: int, limit: int, page: int) -> str:
    query = urllib.parse.urlencode(
        {
            "filter[institution]": str(institution_id),
            "limit": str(limit),
            "page": str(page),
            "include": "prices",
        }
    )
    return f"{base_url}?{query}"


def fetch_json_url(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_all_pages(base_url: str, institution_id: int, limit: int, timeout: int, sleep_seconds: float) -> dict[str, Any]:
    page = 1
    pages: list[dict[str, Any]] = []
    all_products: list[dict[str, Any]] = []

    while True:
        url = build_url(base_url, institution_id, limit, page)
        payload = fetch_json_url(url, timeout=timeout)
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError(f"Nieoczekiwana odpowiedź API na stronie {page}: pole 'data' nie jest listą")

        meta = payload.get("meta") or {}
        links = payload.get("links")
        pages.append({"page": page, "url": url, "count": len(data), "meta": meta, "links": links})
        all_products.extend(data)

        current_page = int(meta.get("current_page") or page)
        last_page = int(meta.get("last_page") or current_page)
        if current_page >= last_page:
            break

        page += 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return {
        "source": base_url,
        "params": {"filter[institution]": institution_id, "limit": limit, "include": "prices"},
        "fetched_at": utc_now(),
        "pages": pages,
        "data": all_products,
    }


def build_institutions_url(base_url: str, limit: int, page: int) -> str:
    query = urllib.parse.urlencode(
        {
            "include": "address,city",
            "filter[attributes]": "ESHOP,ECO",
            "filter[temporaryDisabled]": "false",
            "page": str(page),
            "limit": str(limit),
        }
    )
    return f"{base_url}?{query}"


def fetch_all_institutions(base_url: str, limit: int, timeout: int, sleep_seconds: float) -> dict[str, Any]:
    page = 1
    pages: list[dict[str, Any]] = []
    institutions: list[dict[str, Any]] = []
    while True:
        url = build_institutions_url(base_url, limit, page)
        payload = fetch_json_url(url, timeout=timeout)
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError(f"Nieoczekiwana odpowiedź API punktów pobrań na stronie {page}: pole 'data' nie jest listą")
        meta = payload.get("meta") or {}
        pages.append({"page": page, "url": url, "count": len(data), "meta": meta})
        institutions.extend(data)
        current_page = int(meta.get("current_page") or page)
        last_page = int(meta.get("last_page") or current_page)
        if current_page >= last_page:
            break
        page += 1
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return {"source": base_url, "fetched_at": utc_now(), "pages": pages, "data": institutions}


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)


def replace_institutions(connection: sqlite3.Connection, snapshot: dict[str, Any]) -> int:
    fetched_at = snapshot.get("fetched_at") or utc_now()
    rows = []
    for institution in snapshot["data"]:
        address = institution.get("address") or {}
        city = address.get("city") or {}
        address_info = address.get("addressInfo")
        if isinstance(address_info, (dict, list)):
            address_info = json_text(address_info)
        rows.append(
            (
                institution["id"], institution.get("externalUuid"), institution.get("databaseId"),
                institution.get("localId"), institution.get("testPriceId"), institution.get("slug"),
                institution.get("name") or "", bool_int(institution.get("temporaryDisabled")),
                address.get("id"), address.get("fullAddress"), address.get("street"), address.get("streetType"),
                address.get("number"), address.get("postalCode"), address_info,
                city.get("id"), city.get("name"), city.get("slug"), json_text(institution), fetched_at,
            )
        )
    connection.execute("DELETE FROM institutions")
    connection.executemany(
        """
        INSERT INTO institutions(
          id, external_uuid, database_id, local_id, test_price_id, slug, name, temporary_disabled,
          address_id, full_address, street, street_type, street_number, postal_code, address_info,
          city_id, city_name, city_slug, raw_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def clear_database(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        for table in TABLES_TO_CLEAR:
            connection.execute(f"DELETE FROM {table}")
        connection.execute("DELETE FROM sqlite_sequence WHERE name = 'fetch_runs'")
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def insert_snapshot(connection: sqlite3.Connection, snapshot: dict[str, Any], institution_id: int, limit: int) -> int:
    products = snapshot["data"]
    fetched_at = snapshot.get("fetched_at") or utc_now()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO fetch_runs(source_url, institution_id, limit_per_page, page_count, total_items, fetched_at, raw_meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot["source"],
            institution_id,
            limit,
            len(snapshot["pages"]),
            len(products),
            fetched_at,
            json_text(snapshot["pages"]),
        ),
    )
    fetch_run_id = int(cursor.lastrowid)

    for product in products:
        thumbnail = product.get("thumbnail") or {}
        media = thumbnail.get("media") if isinstance(thumbnail, dict) else None
        if isinstance(media, dict) and media.get("uuid"):
            cursor.execute(
                """
                INSERT OR REPLACE INTO media(
                  uuid, file_name, mime_type, media_type, path, url, size, name, description, created_at, alt, width, height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    media.get("uuid"),
                    media.get("fileName"),
                    media.get("mimeType"),
                    media.get("type"),
                    media.get("path"),
                    media.get("url"),
                    media.get("size"),
                    media.get("name"),
                    media.get("description"),
                    media.get("createdAt"),
                    media.get("alt"),
                    media.get("width"),
                    media.get("height"),
                ),
            )

        additional_info = product.get("additionalInfo") or {}
        cursor.execute(
            """
            INSERT OR REPLACE INTO products(
              id, uuid, slug, name, type, elab_code, icd_code, global_waiting_time,
              thumbnail_media_uuid, thumbnail_background_color,
              additional_info_content, additional_info_url, additional_info_copy_value,
              raw_product_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product["id"],
                product["uuid"],
                product["slug"],
                product["name"],
                product["type"],
                product["elabCode"],
                product.get("icdCode"),
                product.get("globalWaitingTime"),
                media.get("uuid") if isinstance(media, dict) else None,
                thumbnail.get("backgroundColor") if isinstance(thumbnail, dict) else None,
                additional_info.get("content") if isinstance(additional_info, dict) else None,
                additional_info.get("url") if isinstance(additional_info, dict) else None,
                additional_info.get("copyValue") if isinstance(additional_info, dict) else None,
                json_text(product),
                fetched_at,
            ),
        )

    for product in products:
        prices = product.get("prices") or {}
        sale_gross, sale_currency = money(prices, "sale")
        regular_gross, regular_currency = money(prices, "regular")
        minimal_gross, minimal_currency = money(prices, "minimal")
        lowest_gross, lowest_currency = money(prices, "lowest")

        cursor.execute(
            """
            INSERT INTO product_offers(
              fetch_run_id, institution_id, product_id,
              is_ecommerce, requires_material_collection_fee, has_consultation, is_shipping,
              has_block_home_material_collection, has_free_labplus_consultation, has_local_price,
              sale_gross, sale_currency, regular_gross, regular_currency, minimal_gross, minimal_currency,
              lowest_gross, lowest_currency, vat_rate, waiting_time,
              regular_price_message, regular_price_tooltip, sell_state, raw_prices_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fetch_run_id,
                institution_id,
                product["id"],
                bool_int(product.get("isECommerce")),
                bool_int(product.get("requiresMaterialCollectionFee")),
                bool_int(product.get("hasConsultation")),
                bool_int(product.get("isShipping")),
                bool_int(product.get("hasBlockHomeMaterialCollection")),
                bool_int(product.get("hasFreeLabplusConsultation")),
                bool_int(product.get("hasLocalPrice")),
                sale_gross,
                sale_currency,
                regular_gross,
                regular_currency,
                minimal_gross,
                minimal_currency,
                lowest_gross,
                lowest_currency,
                prices.get("vatRate"),
                prices.get("waitingTime"),
                prices.get("regularPriceMessage"),
                prices.get("regularPriceTooltip"),
                prices.get("sellState"),
                json_text(prices),
            ),
        )

        for attribute_code in product.get("institutionAttributes") or []:
            cursor.execute("INSERT OR IGNORE INTO institution_attributes(code) VALUES (?)", (attribute_code,))
            cursor.execute(
                """
                INSERT OR IGNORE INTO product_institution_attributes(fetch_run_id, product_id, attribute_code)
                VALUES (?, ?, ?)
                """,
                (fetch_run_id, product["id"], attribute_code),
            )

        for position, child in enumerate(product.get("products") or []):
            cursor.execute(
                """
                INSERT OR REPLACE INTO package_items(package_id, child_product_id, position, child_status)
                VALUES (?, ?, ?, ?)
                """,
                (product["id"], child["id"], position, child.get("status") or ""),
            )

    return fetch_run_id


def default_json_path(db_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return db_path.with_name(f"diagpl-products-{timestamp}.json")


def sqlite_sidecars(db_path: Path) -> list[Path]:
    return [db_path.with_name(db_path.name + suffix) for suffix in ("-journal", "-wal", "-shm")]


def remove_sqlite_sidecars(db_path: Path) -> None:
    for sidecar in sqlite_sidecars(db_path):
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass


def write_fresh_database(
    db_path: Path,
    snapshot: dict[str, Any],
    institution_id: int,
    limit: int,
    institutions_snapshot: dict[str, Any] | None = None,
) -> tuple[int, dict[str, int]]:
    # Build and validate a complete replacement DB under local /tmp first.
    # Then copy it to a staging file next to the target DB and replace the
    # target, so the database beside the script is never left partially built.
    temp_handle = tempfile.NamedTemporaryFile(prefix="diagpl-products.", suffix=".sqlite", delete=False)
    temp_path = Path(temp_handle.name)
    temp_handle.close()
    staging_path = db_path.with_name(f".{db_path.name}.new")
    try:
        with closing(sqlite3.connect(temp_path, timeout=60)) as connection, connection:
            connection.execute("PRAGMA busy_timeout = 60000")
            connection.execute("PRAGMA foreign_keys = ON")
            create_schema(connection)
            fetch_run_id = insert_snapshot(connection, snapshot, institution_id=institution_id, limit=limit)
            if institutions_snapshot is not None:
                replace_institutions(connection, institutions_snapshot)
            fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if fk_errors:
                raise RuntimeError(f"Kontrola kluczy obcych nie powiodła się: {fk_errors[:10]}")
            counts = {
                "products": connection.execute("SELECT count(*) FROM products").fetchone()[0],
                "offers": connection.execute("SELECT count(*) FROM product_offers").fetchone()[0],
                "package_items": connection.execute("SELECT count(*) FROM package_items").fetchone()[0],
                "attributes": connection.execute("SELECT count(*) FROM institution_attributes").fetchone()[0],
                "media": connection.execute("SELECT count(*) FROM media").fetchone()[0],
                "institutions": connection.execute("SELECT count(*) FROM institutions").fetchone()[0],
            }
        remove_sqlite_sidecars(db_path)
        shutil.copyfile(temp_path, staging_path)
        staging_path.replace(db_path)
        remove_sqlite_sidecars(db_path)
        return fetch_run_id, counts
    except Exception:
        try:
            staging_path.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        remove_sqlite_sidecars(temp_path)


def format_price(gross: float | None, currency: str | None) -> str:
    if gross is None:
        return "brak ceny"
    amount = f"{gross:.2f}".replace(".", ",")
    return f"{amount} {currency or ''}".strip()


def offer_price_sql(alias: str = "o") -> str:
    return f"""
    CASE
      WHEN {alias}.sale_gross IS NOT NULL THEN {alias}.sale_gross
      WHEN {alias}.regular_gross IS NOT NULL THEN {alias}.regular_gross
      ELSE {alias}.minimal_gross
    END AS display_gross,
    CASE
      WHEN {alias}.sale_gross IS NOT NULL THEN {alias}.sale_currency
      WHEN {alias}.regular_gross IS NOT NULL THEN {alias}.regular_currency
      ELSE {alias}.minimal_currency
    END AS display_currency
    """


def latest_fetch_run_id(connection: sqlite3.Connection, institution_id: int | None = None) -> int:
    if institution_id is None:
        row = connection.execute("SELECT id FROM fetch_runs ORDER BY id DESC LIMIT 1").fetchone()
    else:
        row = connection.execute(
            "SELECT id FROM fetch_runs WHERE institution_id = ? ORDER BY id DESC LIMIT 1", (institution_id,)
        ).fetchone()
    if row is None:
        suffix = f" dla punktu {institution_id}" if institution_id is not None else ""
        raise RuntimeError(f"Baza nie zawiera pobranego katalogu{suffix}. Uruchom: pobierz --punkt {institution_id or 'ID'}")
    return int(row[0])


@contextmanager
def open_existing_db(db: str) -> Iterator[sqlite3.Connection]:
    db_path = Path(db).expanduser().resolve()
    if not db_path.exists():
        raise RuntimeError(f"Baza nie jest zainicjalizowana: {db_path}. Uruchom: inicjalizuj --baza {db_path}")
    connection = sqlite3.connect(db_path, timeout=60)
    connection.execute("PRAGMA busy_timeout = 60000")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


def database_is_initialized(db: str) -> bool:
    db_path = Path(db).expanduser().resolve()
    if not db_path.exists():
        return False
    connection = sqlite3.connect(db_path, timeout=60)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'institutions'"
        ).fetchone()
        if table is None:
            return False
        return connection.execute("SELECT count(*) FROM institutions").fetchone()[0] > 0
    finally:
        connection.close()


def ensure_database_initialized(db: str) -> None:
    if not database_is_initialized(db):
        raise RuntimeError(
            f"Baza nie jest poprawnie zainicjalizowana. Uruchom: inicjalizuj --baza {Path(db).expanduser().resolve()}"
        )


def initialize_database(db: str, timeout: int = 30, sleep_seconds: float = 0.15) -> dict[str, Any]:
    snapshot = fetch_all_institutions(
        base_url=DEFAULT_INSTITUTIONS_URL,
        limit=DEFAULT_LIMIT,
        timeout=timeout,
        sleep_seconds=sleep_seconds,
    )
    db_path = Path(db).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path, timeout=60)) as connection, connection:
        connection.execute("PRAGMA busy_timeout = 60000")
        connection.execute("PRAGMA foreign_keys = ON")
        create_schema(connection)
        replace_institutions(connection, snapshot)
        fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if fk_errors or integrity != "ok":
            raise RuntimeError("Walidacja bazy podczas inicjalizacji nie powiodła się")
    return {
        "db": str(db_path),
        "institution_pages": len(snapshot["pages"]),
        "institutions": len(snapshot["data"]),
    }


def initialize_database_if_needed(db: str, timeout: int = 30, sleep_seconds: float = 0.15) -> dict[str, Any]:
    if database_is_initialized(db):
        with open_existing_db(db) as connection:
            institution_count = connection.execute("SELECT count(*) FROM institutions").fetchone()[0]
        return {"initialized": False, "db": str(Path(db).expanduser().resolve()), "institutions": institution_count}
    return {"initialized": True, **initialize_database(db, timeout=timeout, sleep_seconds=sleep_seconds)}


def run_init(args: argparse.Namespace) -> int:
    print(json.dumps(initialize_database(args.db, timeout=args.timeout, sleep_seconds=args.sleep), ensure_ascii=False, indent=2))
    return 0


def run_list_product(args: argparse.Namespace) -> int:
    with open_existing_db(args.db) as connection:
        fetch_run_id = latest_fetch_run_id(connection)
        rows = connection.execute(
            f"""
            SELECT p.name, {offer_price_sql('o')}
            FROM products p
            JOIN product_offers o ON o.product_id = p.id
            WHERE o.fetch_run_id = ?
              AND o.sell_state = 'available'
            ORDER BY p.name COLLATE NOCASE
            """,
            (fetch_run_id,),
        ).fetchall()

    for name, gross, currency in rows:
        print(f"{name} | {format_price(gross, currency)}")
    return 0


def run_list_institutions(args: argparse.Namespace) -> int:
    with open_existing_db(args.db) as connection:
        rows = connection.execute("SELECT id, name, full_address FROM institutions ORDER BY id").fetchall()
    query = (args.query or "").casefold()
    for institution_id, name, full_address in rows:
        searchable = f"{institution_id} {name or ''} {full_address or ''}".casefold()
        if query and query not in searchable:
            continue
        print(f"{institution_id}\t{name}\t{full_address or ''}")
    return 0


def run_list_packaged(args: argparse.Namespace) -> int:
    with open_existing_db(args.db) as connection:
        fetch_run_id = latest_fetch_run_id(connection)
        package_rows = connection.execute(
            f"""
            SELECT p.id, p.name, {offer_price_sql('o')}
            FROM products p
            JOIN product_offers o ON o.product_id = p.id
            WHERE o.fetch_run_id = ?
              AND p.type = 'package'
              AND o.sell_state = 'available'
            ORDER BY p.name COLLATE NOCASE
            """,
            (fetch_run_id,),
        ).fetchall()

        for package_id, package_name, package_gross, package_currency in package_rows:
            print(f"{package_name} | {format_price(package_gross, package_currency)}")
            item_rows = connection.execute(
                f"""
                SELECT child.name, {offer_price_sql('child_offer')}
                FROM package_items pi
                JOIN products child ON child.id = pi.child_product_id
                JOIN product_offers child_offer ON child_offer.product_id = child.id
                WHERE pi.package_id = ?
                  AND child_offer.fetch_run_id = ?
                ORDER BY pi.position
                """,
                (package_id, fetch_run_id),
            ).fetchall()
            for child_name, child_gross, child_currency in item_rows:
                print(f"  - {child_name} | {format_price(child_gross, child_currency)}")
    return 0


def normalize_lookup(value: str) -> str:
    return " ".join(value.casefold().split())


def resolve_package(connection: sqlite3.Connection, fetch_run_id: int, query: str) -> dict[str, Any]:
    rows = connection.execute(
        f"""
        SELECT p.id, p.name, p.slug, p.elab_code, {offer_price_sql('o')}
        FROM products p
        JOIN product_offers o ON o.product_id = p.id
        WHERE o.fetch_run_id = ?
          AND p.type = 'package'
          AND o.sell_state = 'available'
        ORDER BY p.name COLLATE NOCASE
        """,
        (fetch_run_id,),
    ).fetchall()
    packages = [
        {"id": row[0], "name": row[1], "slug": row[2], "elab_code": row[3], "price": row[4], "currency": row[5]}
        for row in rows
    ]
    query_norm = normalize_lookup(query)
    exact = [
        package
        for package in packages
        if query_norm in {normalize_lookup(package["name"]), normalize_lookup(package["slug"]), normalize_lookup(package["elab_code"])}
    ]
    matches = exact or [package for package in packages if query_norm in normalize_lookup(package["name"])]
    if not matches:
        raise RuntimeError(f"Nie znaleziono dostępnego pakietu: {query}")
    if len(matches) > 1:
        suggestions = "; ".join(package["name"] for package in matches[:10])
        raise RuntimeError(f"Niejednoznaczny pakiet '{query}'. Doprecyzuj nazwę. Pasujące: {suggestions}")
    return matches[0]


def package_items(connection: sqlite3.Connection, fetch_run_id: int, package_id: int) -> list[tuple[str, float | None, str | None]]:
    return connection.execute(
        f"""
        SELECT child.name, {offer_price_sql('child_offer')}
        FROM package_items pi
        JOIN products child ON child.id = pi.child_product_id
        JOIN product_offers child_offer ON child_offer.product_id = child.id
        WHERE pi.package_id = ?
          AND child_offer.fetch_run_id = ?
        ORDER BY pi.position
        """,
        (package_id, fetch_run_id),
    ).fetchall()


def run_package(args: argparse.Namespace) -> int:
    with open_existing_db(args.db) as connection:
        fetch_run_id = latest_fetch_run_id(connection)
        selected_package = resolve_package(connection, fetch_run_id, args.package)
        items = package_items(connection, fetch_run_id, selected_package["id"])

    print(f"{selected_package['name']} | {format_price(selected_package['price'], selected_package['currency'])}")
    child_sum = 0.0
    child_currency = selected_package["currency"] or "PLN"
    for child_name, child_gross, item_currency in items:
        print(f"  - {child_name} | {format_price(child_gross, item_currency)}")
        if child_gross is not None:
            child_sum += float(child_gross)
            child_currency = item_currency or child_currency
    print(f"Suma cen pojedynczych produktów: {format_price(child_sum, child_currency)}")
    return 0


def resolve_requested_products(connection: sqlite3.Connection, fetch_run_id: int, requested: list[str]) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT p.id, p.name, p.slug, p.elab_code, {offer_price_sql('o')}
        FROM products p
        JOIN product_offers o ON o.product_id = p.id
        WHERE o.fetch_run_id = ?
          AND p.type = 'bloodtest'
          AND o.sell_state = 'available'
        """,
        (fetch_run_id,),
    ).fetchall()
    products = [
        {"id": row[0], "name": row[1], "slug": row[2], "elab_code": row[3], "price": row[4], "currency": row[5]}
        for row in rows
    ]
    resolved: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for query in requested:
        query_norm = normalize_lookup(query)
        exact = [
            product
            for product in products
            if query_norm in {normalize_lookup(product["name"]), normalize_lookup(product["slug"]), normalize_lookup(product["elab_code"])}
        ]
        matches = exact or [product for product in products if query_norm in normalize_lookup(product["name"])]
        if not matches:
            raise RuntimeError(f"Nie znaleziono dostępnego produktu: {query}")
        if len(matches) > 1:
            suggestions = "; ".join(product["name"] for product in matches[:10])
            raise RuntimeError(f"Niejednoznaczny produkt '{query}'. Doprecyzuj nazwę. Pasujące: {suggestions}")
        product = matches[0]
        if product["id"] not in seen_ids:
            seen_ids.add(product["id"])
            resolved.append(product)
    return resolved


def package_candidates(connection: sqlite3.Connection, fetch_run_id: int, requested_by_id: dict[int, int]) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT package.id, package.name, package.slug, {offer_price_sql('package_offer')}, child.id, child.name
        FROM products package
        JOIN product_offers package_offer ON package_offer.product_id = package.id
        JOIN package_items pi ON pi.package_id = package.id
        JOIN products child ON child.id = pi.child_product_id
        WHERE package_offer.fetch_run_id = ?
          AND package.type = 'package'
          AND package_offer.sell_state = 'available'
        ORDER BY package.name COLLATE NOCASE, pi.position
        """,
        (fetch_run_id,),
    ).fetchall()

    by_package: dict[int, dict[str, Any]] = {}
    for package_id, package_name, package_slug, gross, currency, child_id, child_name in rows:
        package = by_package.setdefault(
            package_id,
            {"kind": "package", "id": package_id, "name": package_name, "slug": package_slug, "price": gross, "currency": currency, "cover": 0, "covered_names": []},
        )
        if child_id in requested_by_id:
            package["cover"] |= 1 << requested_by_id[child_id]
            package["covered_names"].append(child_name)

    return [candidate for candidate in by_package.values() if candidate["cover"] and candidate["price"] is not None]


def remove_dominated_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        dominated = False
        for other_index, other in enumerate(candidates):
            if index == other_index:
                continue
            candidate_cover = candidate["cover"]
            other_cover = other["cover"]
            if candidate_cover | other_cover == other_cover and candidate["price"] >= other["price"]:
                if candidate_cover != other_cover or candidate["price"] > other["price"] or other_index < index:
                    dominated = True
                    break
        if not dominated:
            kept.append(candidate)
    return kept


def optimize_exact(candidates: list[dict[str, Any]], target_mask: int) -> tuple[float, list[dict[str, Any]]]:
    # Exact weighted set-cover via dynamic programming over bitmasks.
    # This is exponential in the number of requested products, but prunes dominated states.
    dp: dict[int, tuple[float, list[dict[str, Any]]]] = {0: (0.0, [])}
    for candidate in candidates:
        current_states = list(dp.items())
        for mask, (cost, chosen) in current_states:
            new_mask = mask | candidate["cover"]
            new_cost = cost + float(candidate["price"])
            if new_mask not in dp or new_cost < dp[new_mask][0]:
                dp[new_mask] = (new_cost, chosen + [candidate])
    if target_mask not in dp:
        raise RuntimeError("Nie udało się pokryć wszystkich produktów kandydatami optymalizacji")
    return dp[target_mask]


class IlpUnavailableError(RuntimeError):
    def __init__(self) -> None:
        if sys.platform == "win32":
            terminal = "PowerShellu"
            python = "& '" + sys.executable.replace("'", "''") + "'"
        else:
            terminal = "terminalu"
            python = shlex.quote(sys.executable)
        super().__init__(
            "Do dokładnego obliczenia potrzebne są działające pakiety NumPy i SciPy. "
            f"Aby je doinstalować lub zaktualizować, uruchom w {terminal}:\n"
            f"{python} -m pip install --upgrade numpy scipy\n"
            "Następnie uruchom aplikację ponownie."
        )


def optimize_ilp(candidates: list[dict[str, Any]], product_count: int) -> tuple[float, list[dict[str, Any]]]:
    # Exact weighted set-cover via MILP. Requires numpy + scipy.optimize.milp.
    # This scales much better than bitmask DP for larger input lists.
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
    except Exception as exc:  # noqa: BLE001 - optional dependency fallback handled by caller.
        raise IlpUnavailableError() from exc

    if not candidates:
        raise RuntimeError("Brak kandydatów optymalizacji")

    costs = np.array([float(candidate["price"]) for candidate in candidates], dtype=float)
    matrix = np.zeros((product_count, len(candidates)), dtype=float)
    for candidate_index, candidate in enumerate(candidates):
        cover = int(candidate["cover"])
        for product_index in range(product_count):
            if cover & (1 << product_index):
                matrix[product_index, candidate_index] = 1.0

    constraints = LinearConstraint(matrix, lb=np.ones(product_count), ub=np.full(product_count, np.inf))
    result = milp(
        c=costs,
        integrality=np.ones(len(candidates), dtype=int),
        bounds=Bounds(0, 1),
        constraints=constraints,
        options={"time_limit": 120},
    )
    if not result.success or result.x is None:
        raise RuntimeError(f"Algorytm ILP nie znalazł rozwiązania: {result.message}")

    chosen = [candidate for candidate, value in zip(candidates, result.x) if value > 0.5]
    return sum(float(candidate["price"]) for candidate in chosen), chosen


def optimize_greedy(candidates: list[dict[str, Any]], target_mask: int) -> tuple[float, list[dict[str, Any]]]:
    # Approximate weighted set-cover fallback: choose the best price per newly
    # covered requested product until everything is covered.
    remaining = target_mask
    chosen: list[dict[str, Any]] = []
    available = candidates[:]
    while remaining:
        best: dict[str, Any] | None = None
        best_score: float | None = None
        for candidate in available:
            newly_covered = int(candidate["cover"]) & remaining
            new_count = newly_covered.bit_count()
            if new_count == 0:
                continue
            score = float(candidate["price"]) / new_count
            if best_score is None or score < best_score:
                best = candidate
                best_score = score
        if best is None:
            raise RuntimeError("Algorytm zachłanny nie zdołał pokryć wszystkich produktów")
        chosen.append(best)
        remaining &= ~int(best["cover"])
        available.remove(best)
    return sum(float(candidate["price"]) for candidate in chosen), chosen


def optimize_products(
    db: str,
    products: list[str],
    solver: str = "auto",
    max_exact_products: int = 20,
    institution_id: int | None = None,
) -> dict[str, Any]:
    """Return an optimization result shared by the CLI and web UI."""
    with open_existing_db(db) as connection:
        fetch_run_id = latest_fetch_run_id(connection, institution_id)
        requested = resolve_requested_products(connection, fetch_run_id, products)
        if not requested:
            raise RuntimeError("Podaj co najmniej jeden produkt")

        requested_by_id = {product["id"]: index for index, product in enumerate(requested)}
        target_mask = (1 << len(requested)) - 1
        individual_candidates = [
            {
                "kind": "product",
                "id": product["id"],
                "name": product["name"],
                "slug": product["slug"],
                "price": product["price"],
                "currency": product["currency"],
                "cover": 1 << index,
                "covered_names": [product["name"]],
            }
            for index, product in enumerate(requested)
        ]
        candidates = remove_dominated_candidates(individual_candidates + package_candidates(connection, fetch_run_id, requested_by_id))
        original_sum = sum(float(product["price"]) for product in requested)
        selected_solver = solver
        if solver == "auto":
            selected_solver = "exact" if len(requested) <= max_exact_products else "ilp"
        warning = None
        if selected_solver == "exact":
            optimized_sum, chosen = optimize_exact(candidates, target_mask)
        elif selected_solver == "ilp":
            try:
                optimized_sum, chosen = optimize_ilp(candidates, len(requested))
            except IlpUnavailableError as exc:
                if solver != "auto":
                    raise
                selected_solver = "greedy"
                optimized_sum, chosen = optimize_greedy(candidates, target_mask)
                warning = f"Wynik jest przybliżony i może nie być najtańszy. {exc}"
        elif selected_solver == "greedy":
            optimized_sum, chosen = optimize_greedy(candidates, target_mask)
        else:
            raise RuntimeError(f"Nieznany algorytm: {selected_solver}")

    currency = requested[0]["currency"] or "PLN"
    return {
        "solver": selected_solver,
        "solver_note": {"exact": "exact DP", "ilp": "ILP exact", "greedy": "greedy approximate"}[selected_solver],
        "warning": warning,
        "currency": currency,
        "original_sum": original_sum,
        "optimized_sum": optimized_sum,
        "savings": original_sum - optimized_sum,
        "requested": requested,
        "chosen": sorted(chosen, key=lambda value: (value["kind"] != "package", value["name"].casefold())),
    }


def run_optimize(args: argparse.Namespace) -> int:
    result = optimize_products(
        args.db,
        args.products,
        POLISH_SOLVERS[args.solver],
        args.max_exact_products,
    )
    method_names = {
        "exact DP": "dokładny DP",
        "ILP exact": "dokładny ILP",
        "greedy approximate": "przybliżony algorytm zachłanny",
    }
    print(f"Algorytm: {method_names.get(result['solver_note'], result['solver_note'])}")
    if result["warning"]:
        print(f"Uwaga: {result['warning']}")
    elif result["solver"] == "greedy":
        print("Uwaga: algorytm zachłanny jest przybliżony — wynik może nie być globalnie optymalny.")
    print(f"Suma cen podanych produktów: {format_price(result['original_sum'], result['currency'])}")
    print(f"Suma cen proponowanego zestawu: {format_price(result['optimized_sum'], result['currency'])}")
    print(f"Oszczędność: {format_price(result['savings'], result['currency'])}")
    print("Mieszanka:")
    for item in result["chosen"]:
        label = "Pakiet" if item["kind"] == "package" else "Produkt"
        print(f"- {label}: {item['name']} | {format_price(item['price'], item['currency'])}")
        if item["kind"] == "package":
            print(f"  pokrywa: {', '.join(item['covered_names'])}")
    return 0


def search_products(db: str, query: str = "", limit: int = 30) -> list[dict[str, Any]]:
    """Search available blood tests for the web UI."""
    with open_existing_db(db) as connection:
        fetch_run_id = latest_fetch_run_id(connection)
        rows = connection.execute(
            f"""
            SELECT p.name, p.slug, p.elab_code, {offer_price_sql('o')}
            FROM products p
            JOIN product_offers o ON o.product_id = p.id
            WHERE o.fetch_run_id = ?
              AND p.type = 'bloodtest'
              AND o.sell_state = 'available'
              AND (? = '' OR p.name LIKE ? COLLATE NOCASE OR p.elab_code LIKE ? COLLATE NOCASE)
            ORDER BY
              CASE WHEN p.name LIKE ? COLLATE NOCASE THEN 0 ELSE 1 END,
              p.name COLLATE NOCASE
            LIMIT ?
            """,
            (fetch_run_id, query, f"%{query}%", f"%{query}%", f"{query}%", limit),
        ).fetchall()
    return [
        {"name": name, "slug": slug, "elab_code": elab_code, "price": gross, "currency": currency}
        for name, slug, elab_code, gross, currency in rows
    ]


def search_institutions(db: str, query: str = "", limit: int = 30) -> list[dict[str, Any]]:
    """Search initialized institutions using Unicode-aware substring matching."""
    with open_existing_db(db) as connection:
        rows = connection.execute(
            "SELECT id, name, full_address, city_name FROM institutions ORDER BY name COLLATE NOCASE"
        ).fetchall()
    normalized = query.strip().casefold()
    matches: list[tuple[int, str, tuple[Any, ...]]] = []
    for row in rows:
        institution_id, name, full_address, city_name = row
        name_text = (name or "").casefold()
        address_text = (full_address or "").casefold()
        searchable = f"{institution_id} {name_text} {address_text} {(city_name or '').casefold()}"
        if normalized and normalized not in searchable:
            continue
        rank = 0 if name_text.startswith(normalized) else 1 if normalized in name_text else 2 if address_text.startswith(normalized) else 3
        matches.append((rank, name_text, row))
    matches.sort(key=lambda value: (value[0], value[1]))
    return [
        {"id": row[0], "name": row[1], "full_address": row[2], "city_name": row[3]}
        for _, _, row in matches[:limit]
    ]


def get_institution(db: str, institution_id: int) -> dict[str, Any] | None:
    with open_existing_db(db) as connection:
        row = connection.execute(
            "SELECT id, name, full_address, city_name FROM institutions WHERE id = ?", (institution_id,)
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "name": row[1], "full_address": row[2], "city_name": row[3]}


def database_status(db: str) -> dict[str, Any]:
    with open_existing_db(db) as connection:
        row = connection.execute(
            "SELECT fetched_at, total_items, institution_id FROM fetch_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        has_institutions = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'institutions'"
        ).fetchone()
        institution_count = connection.execute("SELECT count(*) FROM institutions").fetchone()[0] if has_institutions else 0
        selected_row = (
            connection.execute("SELECT id, name, full_address FROM institutions WHERE id = ?", (row[2],)).fetchone()
            if row
            else None
        )
    return {
        "fetched_at": row[0] if row else None,
        "total_items": row[1] if row else 0,
        "institutions": institution_count,
        "selected_institution": (
            {"id": selected_row[0], "name": selected_row[1], "full_address": selected_row[2]}
            if selected_row
            else None
        ),
    }


def refresh_database(db: str, institution_id: int) -> dict[str, Any]:
    """Fetch products and institutions, then atomically replace the database."""
    snapshot = fetch_all_pages(DEFAULT_BASE_URL, institution_id, DEFAULT_LIMIT, timeout=30, sleep_seconds=0.15)
    institutions_snapshot = fetch_all_institutions(DEFAULT_INSTITUTIONS_URL, DEFAULT_LIMIT, timeout=30, sleep_seconds=0.15)
    fetch_run_id, counts = write_fresh_database(
        Path(db).expanduser().resolve(), snapshot, institution_id, DEFAULT_LIMIT, institutions_snapshot
    )
    return {
        "fetch_run_id": fetch_run_id,
        "pages": len(snapshot["pages"]),
        "items": len(snapshot["data"]),
        "institution_pages": len(institutions_snapshot["pages"]),
        "institutions": len(institutions_snapshot["data"]),
        "counts": counts,
    }


def run_fetch(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    snapshot = fetch_all_pages(
        base_url=args.base_url,
        institution_id=args.institution,
        limit=args.limit,
        timeout=args.timeout,
        sleep_seconds=args.sleep,
    )
    institutions_snapshot = fetch_all_institutions(
        DEFAULT_INSTITUTIONS_URL, DEFAULT_LIMIT, timeout=args.timeout, sleep_seconds=args.sleep
    )

    json_path: Path | None = None
    if args.json is not None:
        json_path = default_json_path(db_path) if args.json == "" else Path(args.json).expanduser().resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.clear:
        fetch_run_id, counts = write_fresh_database(
            db_path, snapshot, institution_id=args.institution, limit=args.limit, institutions_snapshot=institutions_snapshot
        )
    else:
        with closing(sqlite3.connect(db_path, timeout=60)) as connection, connection:
            connection.execute("PRAGMA busy_timeout = 60000")
            connection.execute("PRAGMA foreign_keys = ON")
            create_schema(connection)
            fetch_run_id = insert_snapshot(connection, snapshot, institution_id=args.institution, limit=args.limit)
            replace_institutions(connection, institutions_snapshot)
            fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if fk_errors:
                raise RuntimeError(f"Kontrola kluczy obcych nie powiodła się: {fk_errors[:10]}")
            counts = {
                "products": connection.execute("SELECT count(*) FROM products").fetchone()[0],
                "offers": connection.execute("SELECT count(*) FROM product_offers").fetchone()[0],
                "package_items": connection.execute("SELECT count(*) FROM package_items").fetchone()[0],
                "attributes": connection.execute("SELECT count(*) FROM institution_attributes").fetchone()[0],
                "media": connection.execute("SELECT count(*) FROM media").fetchone()[0],
                "institutions": connection.execute("SELECT count(*) FROM institutions").fetchone()[0],
            }

    result = {
        "db": str(db_path),
        "json": str(json_path) if json_path else None,
        "fetch_run_id": fetch_run_id,
        "pages": len(snapshot["pages"]),
        "items": len(snapshot["data"]),
        "institution_pages": len(institutions_snapshot["pages"]),
        "institutions": len(institutions_snapshot["data"]),
        "counts": counts,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = PolishArgumentParser(
        epilog="Jeśli baza nie jest poprawnie zainicjalizowana, najpierw uruchom komendę inicjalizuj."
    )
    subparsers = parser.add_subparsers(dest="komenda", title="komendy", metavar="KOMENDA")

    init = subparsers.add_parser(
        "inicjalizuj",
        help="Zainicjalizuj bazę, pobierając listę punktów pobrań. Uruchom tę komendę jako pierwszą.",
    )
    init.add_argument("--baza", dest="db", default=DEFAULT_DB, metavar="PLIK", help=f"ścieżka do bazy SQLite; domyślnie: {DEFAULT_DB}")
    init.add_argument("--czas-oczekiwania", dest="timeout", type=int, default=30, metavar="SEKUNDY", help="limit czasu żądania HTTP w sekundach; domyślnie: 30")
    init.add_argument("--opoznienie", dest="sleep", type=float, default=0.15, metavar="SEKUNDY", help="przerwa między żądaniami stron; domyślnie: 0,15")
    init.set_defaults(func=run_init)

    fetch = subparsers.add_parser("pobierz", help="Pobierz wszystkie strony API i odśwież bazę SQLite.")
    fetch.add_argument("--baza", dest="db", default=DEFAULT_DB, metavar="PLIK", help=f"ścieżka do bazy SQLite; domyślnie: {DEFAULT_DB}")
    fetch.add_argument("--plik-json", dest="json", nargs="?", const="", default=None, metavar="PLIK", help="zapisz także pełny katalog do JSON; bez ścieżki utworzy datowany plik obok bazy")
    fetch.add_argument("--punkt", dest="institution", type=int, required=True, metavar="ID", help="identyfikator punktu pobrań DIAG.pl")
    fetch.add_argument("--liczba-na-strone", dest="limit", type=int, default=DEFAULT_LIMIT, metavar="LICZBA", help=f"liczba pozycji na stronę; domyślnie: {DEFAULT_LIMIT}")
    fetch.add_argument("--adres-api", dest="base_url", default=DEFAULT_BASE_URL, metavar="URL", help="bazowy adres API")
    fetch.add_argument("--czas-oczekiwania", dest="timeout", type=int, default=30, metavar="SEKUNDY", help="limit czasu żądania HTTP w sekundach; domyślnie: 30")
    fetch.add_argument("--opoznienie", dest="sleep", type=float, default=0.15, metavar="SEKUNDY", help="przerwa między żądaniami stron; domyślnie: 0,15")
    clear = fetch.add_mutually_exclusive_group()
    clear.add_argument("--wyczysc", dest="clear", action="store_true", help="usuń stare dane przed zapisem; ustawienie domyślne")
    clear.add_argument("--zachowaj", dest="clear", action="store_false", help="zachowaj wcześniejsze pobrania w bazie")
    fetch.set_defaults(func=run_fetch, clear=True)

    list_institutions = subparsers.add_parser("lista-punktow", help="Wyświetl punkty pobrań wraz z identyfikatorem, nazwą i adresem.")
    list_institutions.add_argument("--baza", dest="db", default=DEFAULT_DB, metavar="PLIK", help=f"ścieżka do bazy SQLite; domyślnie: {DEFAULT_DB}")
    list_institutions.add_argument("--szukaj", dest="query", metavar="TEKST", help="pokaż punkty zawierające tekst w identyfikatorze, nazwie lub adresie")
    list_institutions.set_defaults(func=run_list_institutions)

    list_products = subparsers.add_parser("lista-badan", help="Wyświetl dostępne badania i ich aktualne ceny.")
    list_products.add_argument("--baza", dest="db", default=DEFAULT_DB, metavar="PLIK", help=f"ścieżka do bazy SQLite; domyślnie: {DEFAULT_DB}")
    list_products.set_defaults(func=run_list_product)

    list_packages = subparsers.add_parser("lista-pakietow", help="Wyświetl dostępne pakiety, ich skład i aktualne ceny.")
    list_packages.add_argument("--baza", dest="db", default=DEFAULT_DB, metavar="PLIK", help=f"ścieżka do bazy SQLite; domyślnie: {DEFAULT_DB}")
    list_packages.set_defaults(func=run_list_packaged)

    package = subparsers.add_parser("pakiet", help="Wyświetl wybrany pakiet, jego cenę i ceny badań składowych.")
    package.add_argument("--baza", dest="db", default=DEFAULT_DB, metavar="PLIK", help=f"ścieżka do bazy SQLite; domyślnie: {DEFAULT_DB}")
    package.add_argument("package", metavar="PAKIET", help="nazwa, skrót adresu, kod eLab albo jednoznaczny fragment nazwy pakietu")
    package.set_defaults(func=run_package)

    optimize = subparsers.add_parser("optymalizuj", help="Znajdź najtańszy zestaw badań i pakietów pokrywający podaną listę.")
    optimize.add_argument("--baza", dest="db", default=DEFAULT_DB, metavar="PLIK", help=f"ścieżka do bazy SQLite; domyślnie: {DEFAULT_DB}")
    optimize.add_argument("--algorytm", dest="solver", choices=tuple(POLISH_SOLVERS), default="automatyczny", help="metoda optymalizacji; tryb automatyczny wybiera najlepszą dostępną metodę; domyślnie: automatyczny")
    optimize.add_argument("--maks-dokladnych-badan", dest="max_exact_products", type=int, default=20, metavar="LICZBA", help="maksymalna liczba badań dla dokładnego DP w trybie automatycznym; domyślnie: 20")
    optimize.add_argument("products", nargs="+", metavar="BADANIE", help="nazwy, skróty adresów lub kody eLab badań; dopuszczalny jest jednoznaczny fragment nazwy")
    optimize.set_defaults(func=run_optimize)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.komenda is None:
        parser.print_help()
        return 0
    try:
        if args.komenda != "inicjalizuj":
            ensure_database_initialized(args.db)
        return args.func(args)
    except BrokenPipeError:
        return 0
    except Exception as exc:  # noqa: BLE001 - command-line tool should print concise errors.
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
