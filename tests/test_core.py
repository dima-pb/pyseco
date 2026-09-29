import asyncio
import sqlite3

import pytest

import accounts
import config
import db
from conftest import Harness, write_config


def run(coro):
  return asyncio.run(coro)
#


# ---- database ----

def test_migrations_run_once_and_in_order(tmp_path):
  async def scenario():
    database = db.Database(str(tmp_path / 'test.db'))
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
  run(scenario())
#


def test_failed_migration_changes_nothing(tmp_path):
  async def scenario():
    database = db.Database(str(tmp_path / 'test.db'))
    await database.open()
    await database.migrate('comp', ['CREATE TABLE t (a INTEGER);'])
    with pytest.raises(sqlite3.Error):
      await database.migrate('comp', ['CREATE TABLE t (a INTEGER);', 'CREATE TABLE u (x); THIS IS NOT SQL;'])
    #
    assert await database.fetchone("SELECT name FROM sqlite_master WHERE name = 'u'") is None
    assert (await database.fetchone("SELECT version FROM schema_versions WHERE component = 'comp'"))[0] == 1
    await database.close()
  #
  run(scenario())
#


# ---- settings ----

def test_config_reads_sections_and_resolves_paths(tmp_path):
  cfg = config.Config(write_config(tmp_path, 5000, '[discord]\ntoken = "x"\n'))
  assert cfg.port == 5000
  assert cfg.masteradmins == ['master']
  assert cfg.data_dir == str(tmp_path / 'data')
  assert cfg.section('discord') == {'token': 'x'}
  assert cfg.section('missing') == {}
#


def test_config_errors_are_readable(tmp_path):
  with pytest.raises(config.ConfigError, match='not found'):
    config.Config(str(tmp_path / 'nope.toml'))
  #
  bad = tmp_path / 'bad.toml'
  bad.write_text('[server\n')
  with pytest.raises(config.ConfigError, match='not valid TOML'):
    config.Config(str(bad))
  #
#


# ---- accounts ----

def test_roles_and_staff(tmp_path):
  async def scenario():
    database = db.Database(str(tmp_path / 'test.db'))
    await database.open()
    acc = accounts.Accounts(database, ['boss'])
    await acc.start()
    assert await acc.role('boss') == accounts.MASTERADMIN
    assert await acc.role('nobody') == accounts.PLAYER
    await acc.player_seen('op', '$f00Op', visit=True)
    await acc.set_role('op', accounts.OPERATOR)
    await acc.set_role('adm', accounts.ADMIN) # never seen before
    assert await acc.role('adm') == accounts.ADMIN
    with pytest.raises(ValueError):
      await acc.set_role('boss', accounts.PLAYER)
    #
    assert [(login, role) for login, _, role in await acc.staff()] == [
      ('boss', accounts.MASTERADMIN), ('adm', accounts.ADMIN), ('op', accounts.OPERATOR)]
    await database.close()
  #
  run(scenario())
#


def test_discord_link_codes(tmp_path):
  async def scenario():
    database = db.Database(str(tmp_path / 'test.db'))
    await database.open()
    acc = accounts.Accounts(database, [])
    await acc.start()
    code = acc.create_link_code('alice')
    assert await acc.redeem_link_code('999999' if code != '999999' else '111111', 42) is None
    assert await acc.redeem_link_code(code, 42) == 'alice'
    assert await acc.redeem_link_code(code, 43) is None # codes work once
    assert await acc.login_for_discord(42) == 'alice'
    assert await acc.unlink_discord(42)
    assert await acc.login_for_discord(42) is None
    await database.close()
  #
  run(scenario())
#


# ---- controller with a fake server ----

def test_login_failure_is_fatal(tmp_path):
  async def scenario():
    import log, pyseco
    from fake_server import FakeServer
    server = FakeServer(password='other')
    await server.start()
    cfg = config.Config(write_config(tmp_path, server.port))
    controller = pyseco.TMController(cfg, log.Logging(cfg.log_path, cfg.log_level))
    with pytest.raises(pyseco.AuthenticationError, match='Password incorrect'):
      await asyncio.wait_for(controller.run(), 5)
    #
    assert not server.called('EnableCallbacks') # nothing happens without a login
    await server.stop()
  #
  run(scenario())
#


def test_login_before_callbacks(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      names = [name for name, _ in h.server.calls]
      assert names.index('Authenticate') < names.index('EnableCallbacks')
    #
  #
  run(scenario())
#


def test_chat_commands_and_permissions(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      await h.chat('bob', '/setrole carl admin')
      assert 'masteradmin' in h.replies_to('bob')[-1] # bob is only a player
      await h.chat('master', '/setrole bob operator')
      assert h.replies_to('master')[-1].endswith('bob is now operator.')
      assert await h.controller.accounts.role('bob') == accounts.OPERATOR
      await h.chat('master', '/setrole bob king')
      assert 'Usage: /setrole <login> <player|operator|admin>' in h.replies_to('master')[-1]
      await h.chat('bob', '/staff')
      assert any('masteradmin: master' in r for r in h.replies_to('bob'))
      count = len(h.server.called('ChatSendServerMessageToLogin'))
      await h.chat('bob', '/unknowncommand') # may belong to XAseco
      await h.chat('bob', 'hello /setrole')  # not a command
      await h.chat('bob', '/setrole bob admin', uid=0) # the server's own message
      assert len(h.server.called('ChatSendServerMessageToLogin')) == count
    #
  #
  run(scenario())
#


def test_help_shows_only_allowed_commands(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      await h.chat('bob', '/pyseco')
      assert not any('/setrole' in r for r in h.replies_to('bob'))
      await h.chat('master', '/pyseco')
      assert any('/setrole' in r for r in h.replies_to('master'))
      assert not any('!whoami' in r or '/help' in r for r in h.replies_to('master')) # discord only
    #
  #
  run(scenario())
#


def test_link_code_from_game(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      await h.chat('alice', '/link')
      code = h.replies_to('alice')[-1].split('!link ')[1].split('$')[0]
      assert await h.controller.accounts.redeem_link_code(code, 7) == 'alice'
    #
  #
  run(scenario())
#


def test_players_are_remembered(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      info = {'Login': 'dave', 'NickName': '$f00Dave', 'PlayerId': 3, 'TeamId': -1, 'SpectatorStatus': 0,
        'LadderRanking': 0, 'Flags': 0}
      h.server.handlers['GetPlayerInfo'] = lambda login, version: info
      await h.server.callback('TrackMania.PlayerConnect', 'dave', False)
      await h.server.callback('TrackMania.PlayerInfoChanged', info)
      await h.settle()
      row = await h.controller.db.fetchone('SELECT nickname, visits FROM players WHERE login = ?', ('dave',))
      assert (row['nickname'], row['visits']) == ('$f00Dave', 1)
    #
  #
  run(scenario())
#


def test_waits_for_a_server_that_is_still_starting(tmp_path):
  async def scenario():
    import socket, log, pyseco
    from fake_server import FakeServer
    with socket.socket() as sock: # a free port, nobody listens yet
      sock.bind(('127.0.0.1', 0))
      port = sock.getsockname()[1]
    #
    cfg = config.Config(write_config(tmp_path, port))
    controller = pyseco.TMController(cfg, log.Logging(cfg.log_path, cfg.log_level))
    task = asyncio.create_task(controller.run())
    await asyncio.sleep(2.5) # controller retries meanwhile
    server = FakeServer()
    await server.start(port)
    await asyncio.wait_for(server.connected.wait(), 5)
    await asyncio.sleep(0.2)
    assert server.called('EnableCallbacks')
    await controller.stop()
    await asyncio.wait_for(task, 5)
    await server.stop()
  #
  run(scenario())
#
