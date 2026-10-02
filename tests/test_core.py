import asyncio

import pytest

from core import config, roles
from core.controller import AuthenticationError, Controller
from services import accounts
from conftest import Harness, texts, write_config


def run(coro):
  return asyncio.run(coro)
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
  with pytest.raises(config.ConfigError, match='backend must be one of sqlite, memory'):
    config.Config(write_config(tmp_path, 5000, '[storage]\nbackend = "postgres"\n'))
  #
#


# ---- accounts (on top of any storage backend) ----

@pytest.fixture(params=['sqlite', 'memory'])
def make_storage(request, tmp_path):
  from storage.memory import MemoryStorage
  from storage.sqlite import SqliteStorage
  return lambda: SqliteStorage(str(tmp_path / 'test.db')) if request.param == 'sqlite' else MemoryStorage()
#


def test_roles_and_staff(make_storage):
  async def scenario():
    storage = make_storage()
    await storage.open()
    acc = accounts.Accounts(storage.players, ['boss'])
    assert await acc.role('boss') == roles.MASTERADMIN
    assert await acc.role('nobody') == roles.PLAYER
    await acc.player_seen('op', '$f00Op', visit=True)
    await acc.set_role('op', roles.OPERATOR)
    await acc.set_role('adm', roles.ADMIN) # never seen before
    assert await acc.role('adm') == roles.ADMIN
    with pytest.raises(ValueError):
      await acc.set_role('boss', roles.PLAYER)
    #
    with pytest.raises(ValueError):
      await acc.set_role('op', roles.MASTERADMIN)
    #
    assert [(login, role) for login, _, role in await acc.staff()] == [
      ('boss', roles.MASTERADMIN), ('adm', roles.ADMIN), ('op', roles.OPERATOR)]
    await storage.close()
  #
  run(scenario())
#


def test_discord_link_codes(make_storage):
  async def scenario():
    storage = make_storage()
    await storage.open()
    acc = accounts.Accounts(storage.players, [])
    code = acc.create_link_code('alice')
    assert await acc.redeem_link_code('999999' if code != '999999' else '111111', 42) is None
    assert await acc.redeem_link_code(code, 42) == 'alice'
    assert await acc.redeem_link_code(code, 43) is None # codes work once
    assert await acc.login_for_discord(42) == 'alice'
    assert await acc.unlink_discord(42)
    assert await acc.login_for_discord(42) is None
    await storage.close()
  #
  run(scenario())
#


# ---- controller with a fake server ----

def test_login_failure_is_fatal(tmp_path):
  async def scenario():
    from core import log
    from fake_server import FakeServer
    server = FakeServer(password='other')
    await server.start()
    cfg = config.Config(write_config(tmp_path, server.port))
    controller = Controller(cfg, log.Logging(cfg.log_path, cfg.log_level))
    with pytest.raises(AuthenticationError, match='Password incorrect'):
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
      assert await h.controller.accounts.role('bob') == roles.OPERATOR
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
      assert not any('setrole' in t for t in texts(h.manialink('bob')))
      await h.chat('master', '/pyseco')
      shown = texts(h.manialink('master'))
      assert '$fff/setrole <login> <player|operator|admin>' in shown and '$dddgives a player a role' in shown
      assert not any('whoami' in t or 'help' in t for t in shown) # discord only
    #
  #
  run(scenario())
#


def test_commands_of_plugins_that_are_not_loaded_are_unknown(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      await h.chat('alice', '/pyseco')
      assert not any('/link' in t for t in texts(h.manialink('alice'))) # belongs to the discord plugin
      count = len(h.replies_to('alice'))
      await h.chat('alice', '/link')
      assert len(h.replies_to('alice')) == count
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
      assert (await h.controller.storage.players.get('dave')).nickname == '$f00Dave'
    #
  #
  run(scenario())
#


def test_waits_for_a_server_that_is_still_starting(tmp_path):
  async def scenario():
    import socket
    from core import log
    from fake_server import FakeServer
    with socket.socket() as sock: # a free port, nobody listens yet
      sock.bind(('127.0.0.1', 0))
      port = sock.getsockname()[1]
    #
    cfg = config.Config(write_config(tmp_path, port))
    controller = Controller(cfg, log.Logging(cfg.log_path, cfg.log_level))
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



# ---- events, players, chat ----

def test_a_failing_handler_does_not_stop_the_others(tmp_path):
  async def scenario():
    from core import events, log
    got = []
    async def broken(data):
      raise RuntimeError('broken')
    #
    async def working(data):
      got.append(data)
    #
    bus = events.Events(log.Logging(str(tmp_path), log.LOG_DISABLED))
    bus.register('X', broken)
    bus.register('X', working)
    await bus.emit('X', 42)
    assert got == [42]
  #
  run(scenario())
#


def player_info(login, nickname, player_id):
  return {'Login': login, 'NickName': nickname, 'PlayerId': player_id, 'TeamId': -1, 'SpectatorStatus': 0,
    'LadderRanking': 0, 'Flags': 0}
#


def test_players_join_chat_and_leave(tmp_path):
  async def scenario():
    from core import events
    async with Harness(tmp_path) as h:
      seen = []
      for name in (events.PLAYER_JOINED, events.CHAT, events.PLAYER_LEFT):
        async def record(data, name=name):
          seen.append((name, data))
        #
        h.controller.events.register(name, record)
      #
      h.server.players['eve'] = player_info('eve', '$0f0Eve', 4)
      await h.server.callback('TrackMania.PlayerConnect', 'eve', False)
      await h.server.callback('TrackMania.PlayerInfoChanged', h.server.players['eve'])
      await h.server.callback('TrackMania.PlayerInfoChanged', h.server.players['eve']) # joined only once
      await h.settle()
      assert [(name, p.login) for name, p in seen] == [(events.PLAYER_JOINED, 'eve')]
      assert h.controller.players.count() == 1

      await h.chat('eve', 'hi all')
      await h.chat('eve', '/pyseco') # commands are not chat
      await h.chat('eve', 'from the server', uid=0)
      assert [(m.player.nickname, m.text) for name, m in seen if name == events.CHAT] == [('$0f0Eve', 'hi all')]

      await h.server.callback('TrackMania.PlayerDisconnect', 'eve')
      await h.settle()
      assert seen[-1][0] == events.PLAYER_LEFT and seen[-1][1].login == 'eve'
      assert h.controller.players.count() == 0
    #
  #
  run(scenario())
#


def test_players_on_the_server_at_startup_are_known(tmp_path):
  async def scenario():
    from fake_server import FakeServer
    server = FakeServer()
    server.players['early'] = player_info('early', 'Early Bird', 2)
    async with Harness(tmp_path, server=server) as h:
      assert (await h.controller.players.get('early')).nickname == 'Early Bird'
      assert await h.controller.players.get('nobody') is None
      assert (await h.controller.storage.players.get('early')).nickname == 'Early Bird'
    #
  #
  run(scenario())
#


def test_typed_server_methods(tmp_path):
  async def scenario():
    import xmlrpc.client
    async with Harness(tmp_path) as h:
      server = h.controller.server
      assert (await server.get_current_challenge_info())['UId'] == 'uid1'
      await server.kick('bob') # optional parameters get their default
      assert h.server.called('Kick') == [('bob', '')]
      with pytest.raises(xmlrpc.client.Fault, match='Login unknown'):
        await server.get_player_info('nobody')
      #
      assert h.server.called('GetPlayerInfo')[-1] == ('nobody', 1)
    #
  #
  run(scenario())
#


# ---- ui ----

def test_windows_are_per_player_and_escape_text(tmp_path):
  async def scenario():
    from conftest import action_of
    from services.windows import ListWindow, TextWidget
    async with Harness(tmp_path) as h:
      h.server.players['ann'] = player_info('ann', 'Ann', 7)
      await h.server.callback('TrackMania.PlayerInfoChanged', h.server.players['ann'])
      clicks = []
      async def on_click(login, index):
        clicks.append((login, index))
      #
      window = ListWindow(h.controller.ui, page_size=2)
      other = ListWindow(h.controller.ui)
      assert window.first_action != other.first_action
      await window.open('ann', 'Title <&> "quoted"', ['a & b', '<c>', 'd'], on_click)
      await window.open('ben', 'Other', [('x', 'y')])
      await h.settle()
      page = h.manialink('ann')
      assert '$fffTitle <&> "quoted"' in texts(page) and 'a & b' in texts(page) and '<c>' in texts(page)
      await h.click('ann', action_of(page, 'ArrowNext'))
      await h.click('ann', action_of(h.manialink('ann'), 'd'))
      assert clicks == [('ann', 2)]
      assert texts(h.manialink('ben'))[:2] == ['$fffOther', 'x'] # ben's window is his own

      # one window at a time: another window replaces it
      await other.open('ben', 'Replacing', ['z'])
      assert texts(h.manialink('ben'))[0] == '$fffReplacing'
      assert not window.is_open('ben') and other.is_open('ben')

      await h.server.callback('TrackMania.PlayerDisconnect', 'ann')
      await h.settle()
      assert not window.is_open('ann')

      widget = TextWidget(h.controller.ui, 50, 40)
      await widget.show('12:00')
      xml = h.server.called('SendDisplayManialinkPage')[-1][0]
      assert '12:00' in xml and 'id="' + widget.id + '"' in xml
    #
  #
  run(scenario())
#
