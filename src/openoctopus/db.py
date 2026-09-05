import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY,
  source_url TEXT UNIQUE,
  platform TEXT NOT NULL DEFAULT '1688',
  status TEXT NOT NULL DEFAULT 'new',
  price_rub REAL,
  ozon_product_id TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS source_snapshots(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  raw_json TEXT NOT NULL,
  fetched_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS translations(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  field TEXT NOT NULL,
  zh TEXT DEFAULT '',
  ru TEXT DEFAULT '',
  model TEXT DEFAULT '',
  edited_by_human INTEGER DEFAULT 0,
  UNIQUE(product_id, field));

CREATE TABLE IF NOT EXISTS images(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  kind TEXT NOT NULL DEFAULT 'main',
  source_url TEXT NOT NULL,
  translated_url TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  meta_json TEXT DEFAULT '{}');

CREATE TABLE IF NOT EXISTS category_mappings(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  ozon_category_id TEXT,
  attributes_json TEXT DEFAULT '{}',
  human_confirmed INTEGER DEFAULT 0,
  UNIQUE(product_id));

CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY,
  type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued',
  retries INTEGER DEFAULT 0,
  error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS listings(
  id INTEGER PRIMARY KEY,
  product_id INTEGER REFERENCES products(id),
  import_task_id TEXT,
  result_json TEXT,
  submitted_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS ozon_categories(
  id TEXT PRIMARY KEY,
  parent_id TEXT,
  title TEXT,
  schema_json TEXT DEFAULT '{}',
  synced_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def get_conn(path: str) -> sqlite3.Connection:
    import os

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(path: str) -> None:
    conn = get_conn(path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
