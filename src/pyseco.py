import argparse
import asyncio
import os
import signal
import sys
import traceback
import xmlrpc.client

import client
import config
import log
import messages
import player
from plugins.plugins import Plugins


class AuthenticationError(Exception):
  def __init__(self, username, reason):
    super().__init__('Login as ' + username + ' failed: ' + reason
      + ' - check username_superadmin/password_superadmin in pyseco.cfg against the dedicated server config')
  #
#


class TMController:

  def __init__(self, config, logger, config_dir='.'):
    self.logger = logger
    self.config_dir = config_dir # contains pyseco.cfg, plugin settings are in its plugins/ subdirectory
    self.client = client.TMClient(config.url, config.port, self.queue_callback)
    self.username = config.username_superadmin
    self.password = config.password_superadmin
    self.plugin_names = config.plugins
    self.plugins = None
    self.players = {} # login-string -> player object
    self.events = {} # string -> list of receiver-callbacks (async functions)
    self.callbacks = asyncio.Queue() # server callbacks waiting to be processed, in arrival order

    self.register_event('TrackMania.PlayerConnect', self.player_connect)
    self.register_event('TrackMania.PlayerDisconnect', self.player_disconnect)
    self.register_event('TrackMania.PlayerInfoChanged', self.player_info_changed)
  #

  async def run(self):
    await self.client.connect()
    try:
      await self.login()
    except Exception:
      await self.client.disconnect()
      raise
    #
    players = await self.get_player_list()
    if players is not None:
      for player in players:
        await self.add_player_info(player['Login'], player)
      #
    #

    self.plugins = Plugins(self, self.plugin_names)
    await self.plugins.start()

    dispatcher = asyncio.create_task(self.dispatch_callbacks())
    timer = asyncio.create_task(self.timer())
    try:
      # read_task runs until the connection is lost (ConnectionError) or stop() is called (cancelled)
      await asyncio.wait([self.client.read_task])
      if not self.client.read_task.cancelled():
        self.client.read_task.result() # re-raises the ConnectionError
      #
    finally:
      dispatcher.cancel()
      timer.cancel()
      await self.plugins.stop()
      await self.client.disconnect()
    #
  #

  async def login(self):
    # Without a successful login every admin request would fail later with "Permission denied",
    # which hides the actual cause. So a failed login ends the controller right away.
    try:
      success = await self.client.send(messages.Authenticate(self.username, self.password))
    except xmlrpc.client.Fault as fault:
      raise AuthenticationError(self.username, fault.faultString) from None
    #
    if not success:
      raise AuthenticationError(self.username, 'the server rejected the login')
    #
  #

  async def stop(self):
    # makes run() return
    await self.client.disconnect()
  #

  def plugin_settings_path(self, filename):
    return os.path.join(self.config_dir, 'plugins', filename)
  #

  def queue_callback(self, xml):
    # called by the client's reader task; handlers are run by dispatch_callbacks instead, because
    # a handler that awaits a request would otherwise wait on the very task that has to read the response
    self.callbacks.put_nowait(xml)
  #

  async def dispatch_callbacks(self):
    while True:
      xml = await self.callbacks.get()
      await self.process_callback(messages.deserialize(xml))
    #
  #

  async def timer(self):
    while True:
      await asyncio.sleep(1.0)
      await self.raise_event('second_passed', None)
    #
  #

  async def process_callback(self, cb):
    self.logger.message('Processing callback ' + str(cb), log.LOG_VERBOSE)
    if type(cb) is not tuple or len(cb) != 2:
      self.logger.message('Unexpected callback value ' + str(cb), log.LOG_WARNING)
      return
    #

    event_name = cb[1]
    params = cb[0]
    await self.raise_event(event_name, params)
  #

  def register_event(self, event_name, method):
    if event_name not in self.events:
      self.events[event_name] = []
    #
    self.events[event_name].append(method)
  #

  async def raise_event(self, event_name, params):
    self.logger.message('Raising event ' + event_name + ' with parameters ' + str(params), log.LOG_DEBUG)
    if event_name not in self.events:
      return
    #
    for method in self.events[event_name]:
      # a failing handler (e.g. a plugin) must not take down the controller
      try:
        await method(params)
      except Exception:
        self.logger.message('Handler ' + method.__qualname__ + ' failed on event ' + event_name + ':\n'
          + traceback.format_exc(), log.LOG_ERROR)
      #
    #
  #

  async def get_player_by_login(self, login):
    if login not in self.players:
      self.logger.message('Unlisted player requested ' + login, log.LOG_WARNING)
      info = await self.get_playerinfo(login)
      await self.add_player_info(login, info)
    #
    player = self.players[login]
    if player.nickname is None:
      info = await self.get_playerinfo(login)
      await self.add_player_info(login, info)
    #

    return player
  #

  async def add_player_info(self, login, info):
    if login not in self.players:
      p = player.Player(login)
    else:
      p = self.players[login]
    #
    just_entered = p.id == None
    initialized = False

    if info is not None:
      p.nickname = info['NickName']
      p.id = info['PlayerId']
      initialized = p.id != None
      p.team_id = info['TeamId']
      if 'SpectatorStatus' in info:
        p.is_spec = info['SpectatorStatus'] != 0
      elif 'IsSpectator' in info:
        p.is_spec = info['IsSpectator']
      #
      p.ladder_rank = info['LadderRanking']
      if 'Flags' in info:
        p.flags = info['Flags']
      #
    #
    self.players[login] = p

    if just_entered and initialized:
      await self.raise_event('PlayerConnectComplete', login)
    #
  #

  async def player_connect(self, params):
    login = params[0]
    is_spec = params[1]

    p = player.Player(login, is_spec)
    self.players[login] = p
  #

  async def player_disconnect(self, params):
    p = self.players.pop(params[0], None)
    if p is not None:
      # plugins get the complete player object (nickname etc.), it's no longer in self.players
      await self.raise_event('PlayerDisconnectComplete', p)
    #
  #

  async def player_info_changed(self, params):
    dict = params[0]

    login = dict['Login']
    await self.add_player_info(login, dict)
  #

  async def request(self, message):
    try:
      return await self.client.send(message)
    except Exception as exc:
      self.logger.message(message.method + ' returned with an error ' + str(exc), log.LOG_ERROR)
      return None
    #
  #


  async def authenticate(self, username, password):
    return await self.request(messages.Authenticate(username, password))
  #

  async def list_methods(self):
    return await self.request(messages.ListMethods())
  #

  async def chat_send(self, content):
    return await self.request(messages.ChatSend(content))
  #

  async def get_current_challenge_info(self):
    return await self.request(messages.GetCurrentChallengeInfo())
  #

  async def choose_next_challenge(self, filename):
    return await self.request(messages.ChooseNextChallenge(filename))
  #

  async def next_challenge(self):
    return await self.request(messages.NextChallenge())
  #

  async def restart(self):
    return await self.request(messages.ChallengeRestart())
  #

  async def chat_send_server_message(self, content):
    return await self.request(messages.ChatSendServerMessage(content))
  #

  async def call_vote(self, cmd):
    return await self.request(messages.CallVote(cmd))
  #

  async def call_vote_ex(self, cmd, ratio, timeout, voter):
    return await self.request(messages.CallVoteEx(cmd, ratio, timeout, voter))
  #

  async def current_vote_info(self):
    return await self.request(messages.GetCurrentCallVote())
  #

  async def set_callvote_timeout(self, val):
    return await self.request(messages.SetCallVoteTimeOut(val))
  #

  async def set_callvote_ratio(self, val):
    return await self.request(messages.SetCallVoteRatio(val))
  #

  async def set_callvote_ratios(self, tuple):
    return await self.request(messages.SetCallVoteRatios(tuple))
  #

  async def cancel_vote(self):
    return await self.request(messages.CancelVote())
  #

  async def get_playerinfo(self, login):
    return await self.request(messages.GetPlayerInfo(login))
  #

  async def get_player_list(self):
    return await self.request(messages.GetPlayerList())
  #

  async def send_display_manialink_page(self, xml, duration, hide_on_click):
    return await self.request(messages.SendDisplayManialinkPage(xml, duration, hide_on_click))
  #

  async def send_display_manialink_page_to_login(self, login, xml, duration, hide_on_click):
    return await self.request(messages.SendDisplayManialinkPageToLogin(login, xml, duration, hide_on_click))
  #
#


async def main():
  parser = argparse.ArgumentParser(description='TrackMania Forever server controller')
  parser.add_argument('--config-dir', default='.',
    help='directory with pyseco.cfg and plugins/*.ini, relative log paths are relative to it (default: current directory)')
  args = parser.parse_args()

  cfg = config.Config(os.path.join(args.config_dir, 'pyseco.cfg'))
  logger = log.Logging(os.path.join(args.config_dir, cfg.log_path), cfg.log_level)

  controller = TMController(cfg, logger, args.config_dir)
  # docker and systemd stop programs with SIGTERM: shut down cleanly (plugins, discord logout)
  asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(controller.stop()))
  try:
    await controller.run()
  except AuthenticationError as exc:
    logger.message(str(exc), log.LOG_FATAL)
    return 1
  except Exception as exc:
    logger.message(str(exc), log.LOG_ERROR)
    logger.message(traceback.format_exc(), log.LOG_ERROR)
    return 1
  #
  return 0
#


if __name__ == '__main__':
  try:
    sys.exit(asyncio.run(main()))
  except KeyboardInterrupt:
    pass
  #
#
