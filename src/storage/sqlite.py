import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from storage.interfaces import (Ban, MapStore, ModerationStore, Play, PlayerStore, PlaylistStore, QueuedMap, Record,
  RecordStore, Storage, StoredPlayer)


class Database:
  # sqlite3 is blocking, so every statement runs in one dedicated worker thread. That keeps the
  # event loop free, and since there is only one thread, statements never run concurrently.

  def __init__(self, path):
    self.path = path
    self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='db')
    self.conn = None
  #

  async def open(self):
    await self.run(self._open)
  #

  def _open(self):
    self.conn = sqlite3.connect(self.path, check_same_thread=False)
    self.conn.row_factory = sqlite3.Row
    self.conn.execute('PRAGMA journal_mode=WAL')
    self.conn.execute('PRAGMA foreign_keys=ON')
    with self.conn:
      self.conn.execute('CREATE TABLE IF NOT EXISTS schema_versions (component TEXT PRIMARY KEY, version INTEGER NOT NULL)')
    #
  #

  async def close(self):
    if self.conn is not None:
      await self.run(self.conn.close)
      self.conn = None
    #
    self.executor.shutdown(wait=True)
  #

  async def run(self, function, *args):
    return await asyncio.get_running_loop().run_in_executor(self.executor, function, *args)
  #

  async def execute(self, sql, params=()):
    # runs one statement in its own transaction, returns the cursor (lastrowid, rowcount)
    def work():
      with self.conn:
        return self.conn.execute(sql, params)
      #
    #
    return await self.run(work)
  #

  async def executemany(self, sql, rows):
    def work():
      with self.conn:
        return self.conn.executemany(sql, rows)
      #
    #
    return await self.run(work)
  #

  async def fetchone(self, sql, params=()):
    return await self.run(lambda: self.conn.execute(sql, params).fetchone())
  #

  async def fetchall(self, sql, params=()):
    return await self.run(lambda: self.conn.execute(sql, params).fetchall())
  #

  async def transaction(self, function):
    # runs function(conn) in the worker thread inside one transaction, returns its result
    def work():
      with self.conn:
        return function(self.conn)
      #
    #
    return await self.run(work)
  #

  async def migrate(self, component, migrations):
    # Brings the tables of a component up to date. migrations is a list of SQL scripts: script 1 creates
    # the first version, each further script changes the previous one. Scripts applied before are skipped,
    # so existing data is kept. Never change a released script, append a new one instead.
    def work():
      row = self.conn.execute('SELECT version FROM schema_versions WHERE component = ?', (component,)).fetchone()
      current = row[0] if row else 0
      for version in range(current + 1, len(migrations) + 1):
        # executescript commits on its own, so the script and its version are written in one script
        try:
          self.conn.executescript('BEGIN;\n' + migrations[version - 1] + '\n'
            + 'INSERT INTO schema_versions (component, version) VALUES (' + repr(component) + ', ' + str(version) + ') '
            + 'ON CONFLICT (component) DO UPDATE SET version = excluded.version;\nCOMMIT;')
        except Exception:
          if self.conn.in_transaction:
            self.conn.rollback()
          #
          raise
        #
      #
      return current, len(migrations)
    #
    return await self.run(work)
  #
#


# ---- players ----

PLAYER_MIGRATIONS = [
  # 1
  '''
  CREATE TABLE players (
    login TEXT PRIMARY KEY,
    nickname TEXT NOT NULL DEFAULT '',
    role INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
    visits INTEGER NOT NULL DEFAULT 0
  );
  CREATE TABLE discord_links (
    discord_id INTEGER PRIMARY KEY,
    login TEXT NOT NULL REFERENCES players(login) ON DELETE CASCADE,
    linked_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  ''',
]


class SqlitePlayerStore(PlayerStore):

  def __init__(self, db):
    self.db = db
  #

  async def migrate(self):
    await self.db.migrate('accounts', PLAYER_MIGRATIONS)
  #

  async def seen(self, login, nickname, visit):
    await self.db.execute(
      'INSERT INTO players (login, nickname, visits) VALUES (?, ?, ?) '
      'ON CONFLICT (login) DO UPDATE SET nickname = excluded.nickname, last_seen = datetime(\'now\'), '
      'visits = visits + excluded.visits',
      (login, nickname or '', 1 if visit else 0))
  #

  async def role(self, login):
    row = await self.db.fetchone('SELECT role FROM players WHERE login = ?', (login,))
    return row['role'] if row else 0
  #

  async def set_role(self, login, role):
    await self.db.execute(
      'INSERT INTO players (login, role) VALUES (?, ?) ON CONFLICT (login) DO UPDATE SET role = excluded.role',
      (login, role))
  #

  async def get(self, login):
    row = await self.db.fetchone('SELECT login, nickname, role, visits FROM players WHERE login = ?', (login,))
    return StoredPlayer(row['login'], row['nickname'], row['role'], row['visits']) if row else None
  #

  async def with_role(self):
    rows = await self.db.fetchall('SELECT login, nickname, role, visits FROM players WHERE role > 0')
    return [StoredPlayer(r['login'], r['nickname'], r['role'], r['visits']) for r in rows]
  #

  async def link_discord(self, discord_id, login):
    await self.db.transaction(lambda conn: (
      conn.execute('INSERT OR IGNORE INTO players (login) VALUES (?)', (login,)),
      conn.execute('INSERT INTO discord_links (discord_id, login) VALUES (?, ?) '
        'ON CONFLICT (discord_id) DO UPDATE SET login = excluded.login, linked_at = datetime(\'now\')',
        (discord_id, login))))
  #

  async def login_for_discord(self, discord_id):
    row = await self.db.fetchone('SELECT login FROM discord_links WHERE discord_id = ?', (discord_id,))
    return row['login'] if row else None
  #

  async def unlink_discord(self, discord_id):
    cursor = await self.db.execute('DELETE FROM discord_links WHERE discord_id = ?', (discord_id,))
    return cursor.rowcount > 0
  #
#


# ---- maps ----

MAP_MIGRATIONS = [
  # 1
  '''
  CREATE TABLE maps (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    environment TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE TABLE plays (
    id INTEGER PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES maps(uid),
    played_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX plays_uid ON plays (uid);
  ''',
]


class SqliteMapStore(MapStore):

  def __init__(self, db):
    self.db = db
  #

  async def migrate(self):
    await self.db.migrate('maps', MAP_MIGRATIONS)
  #

  async def known(self, maps):
    await self.db.executemany(
      'INSERT OR IGNORE INTO maps (uid, name, author, environment) VALUES (?, ?, ?, ?)',
      [(m['UId'], m['Name'], m.get('Author', ''), m.get('Environnement', '')) for m in maps])
  #

  async def played(self, uid):
    await self.db.execute('INSERT INTO plays (uid) VALUES (?)', (uid,))
  #

  async def history(self, count):
    rows = await self.db.fetchall(
      'SELECT p.uid, m.name, p.played_at FROM plays p JOIN maps m ON m.uid = p.uid ORDER BY p.id DESC LIMIT ?', (count,))
    return [Play(r['uid'], r['name'], r['played_at']) for r in rows]
  #
#


# ---- playlist (tables and migrations keep their first name, jukebox) ----

PLAYLIST_MIGRATIONS = [
  # 1
  '''
  CREATE TABLE jukebox_queue (
    position INTEGER PRIMARY KEY,
    uid TEXT NOT NULL,
    filename TEXT NOT NULL,
    name TEXT NOT NULL,
    environment TEXT NOT NULL DEFAULT '',
    login TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL
  );
  CREATE TABLE temporary_maps (
    uid TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  ''',
]


class SqlitePlaylistStore(PlaylistStore):

  def __init__(self, db):
    self.db = db
  #

  async def migrate(self):
    await self.db.migrate('jukebox', PLAYLIST_MIGRATIONS)
  #

  async def queue(self):
    rows = await self.db.fetchall('SELECT * FROM jukebox_queue ORDER BY position')
    return [QueuedMap(r['uid'], r['filename'], r['name'], r['environment'], r['login'], r['nickname'], r['source'])
      for r in rows]
  #

  async def set_queue(self, entries):
    await self.db.transaction(lambda conn: (
      conn.execute('DELETE FROM jukebox_queue'),
      conn.executemany('INSERT INTO jukebox_queue (position, uid, filename, name, environment, login, nickname, source) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [(i, e.uid, e.filename, e.name, e.environment, e.login, e.nickname, e.source) for i, e in enumerate(entries)])))
  #

  async def temporary_maps(self):
    return {r['uid']: r['filename'] for r in await self.db.fetchall('SELECT uid, filename FROM temporary_maps')}
  #

  async def add_temporary(self, uid, filename):
    await self.db.execute('INSERT OR REPLACE INTO temporary_maps (uid, filename) VALUES (?, ?)', (uid, filename))
  #

  async def remove_temporary(self, uid):
    await self.db.execute('DELETE FROM temporary_maps WHERE uid = ?', (uid,))
  #
#


# ---- moderation ----

MODERATION_MIGRATIONS = [
  # 1
  '''
  CREATE TABLE bans (
    login TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    by_login TEXT NOT NULL DEFAULT '',
    until TEXT,
    created TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE TABLE mutes (
    login TEXT PRIMARY KEY,
    by_login TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL DEFAULT (datetime('now'))
  );
  ''',
]


class SqliteModerationStore(ModerationStore):

  def __init__(self, db):
    self.db = db
  #

  async def migrate(self):
    await self.db.migrate('moderation', MODERATION_MIGRATIONS)
  #

  async def ban(self, login, reason, by, until):
    await self.db.execute('INSERT OR REPLACE INTO bans (login, reason, by_login, until) VALUES (?, ?, ?, ?)',
      (login, reason, by, until))
  #

  async def unban(self, login):
    return (await self.db.execute('DELETE FROM bans WHERE login = ?', (login,))).rowcount > 0
  #

  async def ban_of(self, login):
    row = await self.db.fetchone("SELECT * FROM bans WHERE login = ? AND (until IS NULL OR until > datetime('now'))",
      (login,))
    return Ban(row['login'], row['reason'], row['by_login'], row['until'], row['created']) if row else None
  #

  async def bans(self):
    rows = await self.db.fetchall("SELECT * FROM bans WHERE until IS NULL OR until > datetime('now') "
      'ORDER BY created DESC, login')
    return [Ban(r['login'], r['reason'], r['by_login'], r['until'], r['created']) for r in rows]
  #

  async def mute(self, login, by):
    await self.db.execute('INSERT OR REPLACE INTO mutes (login, by_login) VALUES (?, ?)', (login, by))
  #

  async def unmute(self, login):
    return (await self.db.execute('DELETE FROM mutes WHERE login = ?', (login,))).rowcount > 0
  #

  async def muted(self):
    return {r['login'] for r in await self.db.fetchall('SELECT login FROM mutes')}
  #
#


# ---- records ----

RECORD_MIGRATIONS = [
  # 1
  '''
  CREATE TABLE records (
    uid TEXT NOT NULL,
    login TEXT NOT NULL,
    time INTEGER NOT NULL,
    checkpoints TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (uid, login)
  );
  CREATE INDEX records_ranking ON records (uid, time, date);
  ''',
]


class SqliteRecordStore(RecordStore):

  def __init__(self, db):
    self.db = db
  #

  async def migrate(self):
    await self.db.migrate('records', RECORD_MIGRATIONS)
  #

  @staticmethod
  def record(row):
    checkpoints = [int(c) for c in row['checkpoints'].split(',')] if row['checkpoints'] else []
    return Record(row['login'], row['nickname'] or row['login'], row['time'], checkpoints, row['date'])
  #

  async def best(self, uid, login):
    row = await self.db.fetchone('SELECT r.*, p.nickname FROM records r LEFT JOIN players p ON p.login = r.login '
      'WHERE r.uid = ? AND r.login = ?', (uid, login))
    return self.record(row) if row else None
  #

  async def save(self, uid, login, time, checkpoints):
    await self.db.execute("INSERT OR REPLACE INTO records (uid, login, time, checkpoints, date) "
      "VALUES (?, ?, ?, ?, datetime('now'))", (uid, login, time, ','.join(str(c) for c in checkpoints)))
  #

  async def ranking(self, uid, limit):
    rows = await self.db.fetchall('SELECT r.*, p.nickname FROM records r LEFT JOIN players p ON p.login = r.login '
      'WHERE r.uid = ? ORDER BY r.time, r.date, r.rowid LIMIT ?', (uid, limit))
    return [self.record(r) for r in rows]
  #
#


class SqliteStorage(Storage):
  # everything in one SQLite file

  def __init__(self, path):
    self.db = Database(path)
    self.players = SqlitePlayerStore(self.db)
    self.maps = SqliteMapStore(self.db)
    self.playlist = SqlitePlaylistStore(self.db)
    self.moderation = SqliteModerationStore(self.db)
    self.records = SqliteRecordStore(self.db)
  #

  async def open(self):
    await self.db.open()
    for store in (self.players, self.maps, self.playlist, self.moderation, self.records):
      await store.migrate()
    #
  #

  async def close(self):
    await self.db.close()
  #
#
