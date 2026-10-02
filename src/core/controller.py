import asyncio
import os
import xmlrpc.client

from core import commands, events, log
from core.server import Server, parse_callback
from plugins.plugins import Plugins
from services import accounts, chat, maps, moderation, players, playlist, race, ui
import storage


class AuthenticationError(Exception):
  def __init__(self, username, reason):
    super().__init__('Login as ' + username + ' failed: ' + reason
      + ' - check login/password in the [server] section of pyseco.toml against the dedicated server config')
  #
#


class Controller:
  # Connects to the server and holds what plugins work with:
  #   server    the dedicated server's methods (core.server_api), e.g. await server.next_challenge()
  #   events    register(name, handler) for core.events and raw server callbacks
  #   commands  register(name, handler, ...) for /commands in game and !commands on discord
  #   storage   what pyseco keeps (storage.interfaces)
  #   services: accounts (roles, discord links), players (who is online), maps (map list, current map,
  #             history), ui (manialinks; windows and widgets in services/windows.py), chat (messages to players),
  #             moderation (kick, mute, ban), playlist (which map comes next, requests for maps),
  #             race (checkpoints and finishes)
  # Plugins use these, never each other.

  def __init__(self, config, logger):
    self.config = config
    self.logger = logger
    self.server = Server(config.url, config.port, self.queue_callback)
    self.events = events.Events(logger)
    self.commands = commands.Commands(logger)
    self.storage = storage.create(config) # everything pyseco keeps, see storage/interfaces.py
    self.callbacks = asyncio.Queue() # server callbacks waiting to be processed, in arrival order

    # services register their event handlers before the plugins, so plugins see an up to date state
    self.accounts = accounts.Accounts(self.storage.players, config.masteradmins)
    self.players = players.Players(self)
    self.maps = maps.Maps(self)
    self.ui = ui.UI(self)
    self.chat = chat.Chat(self)
    self.moderation = moderation.Moderation(self)
    self.playlist = playlist.Playlist(self)
    self.race = race.Race(self)
    self.plugins = Plugins(self, config.plugins)
  #

  def settings(self, section):
    # the plugin's section of pyseco.toml as dict
    return self.config.section(section)
  #

  async def run(self):
    os.makedirs(self.config.data_dir, exist_ok=True)
    await self.storage.open()
    try:
      await self.run_connected()
    finally:
      await self.storage.close()
    #
  #

  async def run_connected(self):
    await self.connect()
    try:
      await self.login()
      # needs a successful login first, servers deny it to connections that are not logged in
      if not await self.server.enable_callbacks(True):
        raise Exception('Unable to enable callbacks')
      #
    except Exception:
      await self.server.disconnect()
      raise
    #
    await self.players.start()
    await self.maps.start()
    await self.moderation.start()
    await self.playlist.start()
    await self.plugins.start()

    dispatcher = asyncio.create_task(self.dispatch_callbacks())
    timer = asyncio.create_task(self.timer())
    try:
      # read_task runs until the connection is lost (ConnectionError) or stop() is called (cancelled)
      await asyncio.wait([self.server.read_task])
      if not self.server.read_task.cancelled():
        self.server.read_task.result() # re-raises the ConnectionError
      #
    finally:
      dispatcher.cancel()
      timer.cancel()
      await self.plugins.stop()
      await self.server.disconnect()
    #
  #

  async def connect(self, wait_seconds=60):
    # the server may still be starting (e.g. both started by docker compose), so retry for a while
    for attempt in range(wait_seconds // 2):
      try:
        await self.server.connect()
        return
      except OSError as exc:
        if attempt == 0:
          self.logger.message('Server not reachable yet (' + str(exc) + '), retrying for ' + str(wait_seconds) + 's',
            log.LOG_INFO)
        #
        await asyncio.sleep(2)
      #
    #
    await self.server.connect()
  #

  async def login(self):
    # Without a successful login every admin request would fail later with "Permission denied",
    # which hides the actual cause. So a failed login ends the controller right away.
    username, password = self.config.username_superadmin, self.config.password_superadmin
    try:
      success = await self.server.authenticate(username, password)
    except xmlrpc.client.Fault as fault:
      raise AuthenticationError(username, fault.faultString) from None
    #
    if not success:
      raise AuthenticationError(username, 'the server rejected the login')
    #
  #

  async def stop(self):
    # makes run() return
    await self.server.disconnect()
  #

  def queue_callback(self, xml):
    # called by the server's reader task; handlers are run by dispatch_callbacks instead, because
    # a handler that awaits a request would otherwise wait on the very task that has to read the response
    self.callbacks.put_nowait(xml)
  #

  async def dispatch_callbacks(self):
    while True:
      xml = await self.callbacks.get()
      try:
        name, params = parse_callback(xml)
      except Exception as exc:
        self.logger.message('Unreadable callback ' + xml[:200] + ': ' + str(exc), log.LOG_WARNING)
        continue
      #
      await self.events.emit(name, params)
    #
  #

  async def timer(self):
    while True:
      await asyncio.sleep(1.0)
      await self.events.emit(events.SECOND_PASSED)
    #
  #
#
