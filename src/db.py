import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor


class Database:
  # SQLite database shared by the controller and all plugins.
  #
  # sqlite3 is blocking, so every statement runs in one dedicated worker thread. That keeps the
  # event loop free, and since there is only one thread, statements never run concurrently.
  # Rows are returned as sqlite3.Row (access by column name or index).

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
    # runs function(conn) in the worker thread inside one transaction, for several statements
    # that must succeed or fail together; returns its result
    def work():
      with self.conn:
        return function(self.conn)
      #
    #
    return await self.run(work)
  #

  async def migrate(self, component, migrations):
    # Brings the tables of a component (the core or a plugin) up to date. migrations is a list of
    # SQL scripts: script 1 creates the first version, each further script changes the previous one.
    # Scripts that were applied before are skipped, so existing data is kept. Never change a script
    # that was released, append a new one instead.
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
