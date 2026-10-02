import asyncio
import sqlite3

import pytest

from storage.interfaces import QueuedMap
from storage.memory import MemoryStorage
from storage.sqlite import Database, SqliteStorage


# Contract tests: every storage backend must pass them. A new backend is added to BACKENDS.

def make_sqlite(tmp_path):
  return SqliteStorage(str(tmp_path / 'test.db'))
#

def make_memory(tmp_path):
  return MemoryStorage()
#

BACKENDS = {'sqlite': make_sqlite, 'memory': make_memory}


@pytest.fixture(params=sorted(BACKENDS))
def make_storage(request, tmp_path):
  return lambda: BACKENDS[request.param](tmp_path)
#


def with_storage(make_storage, scenario):
  async def run():
    storage = make_storage()
    await storage.open()
    try:
      await scenario(storage)
    finally:
      await storage.close()
    #
  #
  asyncio.run(run())
#


def test_players_and_roles(make_storage):
  async def scenario(s):
    assert await s.players.role('nobody') == 0
    assert await s.players.get('nobody') is None
    await s.players.seen('bob', '$f00Bob', True)
    await s.players.seen('bob', '$0f0Bob', False) # nickname follows
    assert (await s.players.get('bob')).nickname == '$0f0Bob'
    await s.players.set_role('bob', 1)
    await s.players.set_role('never_seen', 2) # created on the fly
    assert await s.players.role('never_seen') == 2
    assert sorted((p.login, p.role) for p in await s.players.with_role()) == [('bob', 1), ('never_seen', 2)]
    await s.players.set_role('bob', 0)
    assert [p.login for p in await s.players.with_role()] == ['never_seen']
  #
  with_storage(make_storage, scenario)
#


def test_discord_links(make_storage):
  async def scenario(s):
    assert await s.players.login_for_discord(42) is None
    await s.players.link_discord(42, 'alice')
    assert await s.players.login_for_discord(42) == 'alice'
    assert await s.players.get('alice') is not None # the player exists now
    await s.players.link_discord(42, 'bob') # relinking replaces
    assert await s.players.login_for_discord(42) == 'bob'
    assert await s.players.unlink_discord(42)
    assert not await s.players.unlink_discord(42)
  #
  with_storage(make_storage, scenario)
#


def test_map_history(make_storage):
  async def scenario(s):
    assert await s.maps.history(5) == []
    await s.maps.known([{'UId': 'a', 'Name': 'Map A'}, {'UId': 'b', 'Name': 'Map B', 'Author': 'x'}])
    await s.maps.known([{'UId': 'a', 'Name': 'renamed'}]) # known maps stay as they were
    for uid in ('a', 'b', 'a'):
      await s.maps.played(uid)
    #
    history = await s.maps.history(2)
    assert [(p.uid, p.name) for p in history] == [('a', 'Map A'), ('b', 'Map B')]
    assert len(history[0].played_at) == 19 # YYYY-MM-DD HH:MM:SS
    assert len(await s.maps.history(10)) == 3
  #
  with_storage(make_storage, scenario)
#


def test_playlist_queue_and_temporary_maps(make_storage):
  async def scenario(s):
    assert await s.playlist.queue() == []
    entries = [QueuedMap('u1', 'f1', 'Map 1', 'Stadium', 'bob', 'Bob', 'Jukebox'),
      QueuedMap('u2', 'f2', 'Map 2', '', '', '', 'TMX')]
    await s.playlist.set_queue(entries)
    assert await s.playlist.queue() == entries
    entries.pop() # the stored queue is a copy
    assert len(await s.playlist.queue()) == 2
    await s.playlist.set_queue([])
    assert await s.playlist.queue() == []

    await s.playlist.add_temporary('u1', 'f1')
    await s.playlist.add_temporary('u2', 'f2')
    await s.playlist.remove_temporary('u1')
    await s.playlist.remove_temporary('unknown')
    assert await s.playlist.temporary_maps() == {'u2': 'f2'}
  #
  with_storage(make_storage, scenario)
#


def test_sqlite_keeps_data_across_restarts(tmp_path):
  async def scenario():
    s = make_sqlite(tmp_path)
    await s.open()
    await s.players.set_role('bob', 2)
    await s.close()
    s = make_sqlite(tmp_path)
    await s.open()
    assert await s.players.role('bob') == 2
    await s.close()
  #
  asyncio.run(scenario())
#


# ---- SQLite migrations ----

def test_migrations_run_once_and_in_order(tmp_path):
  async def scenario():
    database = Database(str(tmp_path / 'test.db'))
    await database.open()
    v1 = ['CREATE TABLE t (a INTEGER);']
    assert await database.migrate('comp', v1) == (0, 1)
    await database.execute('INSERT INTO t (a) VALUES (1)')
    assert await database.migrate('comp', v1) == (1, 1) # nothing to do
    v2 = v1 + ['ALTER TABLE t ADD COLUMN b TEXT;']
    assert await database.migrate('comp', v2) == (1, 2)
    row = await database.fetchone('SELECT a, b FROM t')
    assert (row['a'], row['b']) == (1, None) # data kept
    await database.close()
  #
  asyncio.run(scenario())
#


def test_failed_migration_changes_nothing(tmp_path):
  async def scenario():
    database = Database(str(tmp_path / 'test.db'))
    await database.open()
    await database.migrate('comp', ['CREATE TABLE t (a INTEGER);'])
    with pytest.raises(sqlite3.Error):
      await database.migrate('comp', ['CREATE TABLE t (a INTEGER);', 'CREATE TABLE u (x); THIS IS NOT SQL;'])
    #
    assert await database.fetchone("SELECT name FROM sqlite_master WHERE name = 'u'") is None
    assert (await database.fetchone("SELECT version FROM schema_versions WHERE component = 'comp'"))[0] == 1
    await database.close()
  #
  asyncio.run(scenario())
#


def test_bans_and_mutes(make_storage):
  async def scenario(s):
    assert await s.moderation.ban_of('bob') is None
    await s.moderation.ban('bob', 'cheating', 'master', None)
    await s.moderation.ban('old', '', 'master', '2000-01-01 00:00:00') # expired
    await s.moderation.ban('later', 'spam', 'admin', '2999-01-01 00:00:00')
    ban = await s.moderation.ban_of('bob')
    assert (ban.reason, ban.by, ban.until) == ('cheating', 'master', None) and len(ban.created) == 19
    assert await s.moderation.ban_of('old') is None
    assert sorted(b.login for b in await s.moderation.bans()) == ['bob', 'later']
    await s.moderation.ban('bob', 'again', 'admin', None) # replaces
    assert (await s.moderation.ban_of('bob')).reason == 'again'
    assert await s.moderation.unban('bob') and not await s.moderation.unban('bob')
    assert await s.moderation.unban('old') # expired bans can be removed too

    await s.moderation.mute('loud', 'op')
    assert await s.moderation.muted() == {'loud'}
    assert await s.moderation.unmute('loud') and not await s.moderation.unmute('loud')
    assert await s.moderation.muted() == set()
  #
  with_storage(make_storage, scenario)
#


def test_visits_are_counted(make_storage):
  async def scenario(s):
    await s.players.seen('bob', 'Bob', True)
    await s.players.seen('bob', 'Bob', False)
    await s.players.seen('bob', 'Bob', True)
    assert (await s.players.get('bob')).visits == 2
  #
  with_storage(make_storage, scenario)
#
