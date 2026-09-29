import argparse
import asyncio
import os
import signal
import sys
import traceback
import xmlrpc.client

import accounts
import client
import commands
import config
import db
import log
import maps
import messages
import player
import utilities
from plugins.plugins import Plugins


class AuthenticationError(Exception):
  def __init__(self, username, reason):
    super().__init__('Login as ' + username + ' failed: ' + reason
      + ' - check login/password in the [server] section of pyseco.toml against the dedicated server config')
  #
#


class TMController:

  def __init__(self, config, logger):
    self.config = config
    self.logger = logger
    self.db = db.Database(config.database)
    self.accounts = accounts.Accounts(self.db, config.masteradmins)
    self.commands = commands.Commands(logger)
    self.client = client.TMClient(config.url, config.port, self.queue_callback)
    self.maps = None
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
    self.register_event('TrackMania.PlayerChat', self.player_chat)
    self.maps = maps.Maps(self) # registers its events before the plugins, so they see an up to date list
    self.register_core_commands()
  #

  async def run(self):
    os.makedirs(self.config.data_dir, exist_ok=True)
    await self.db.open()
    try:
      await self.accounts.start()
      await self.run_connected()
    finally:
      await self.db.close()
    #
  #
  
  async def run_connected(self):
    await self.connect()
    try:
      await self.login()
      await self.client.enable_callbacks()
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

    await self.maps.start()
    
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

  async def connect(self, wait_seconds=60):
    # the server may still be starting (e.g. both started by docker compose), so retry for a while
    for attempt in range(wait_seconds // 2):
      try:
        await self.client.connect()
        return
      except OSError as exc:
        if attempt == 0:
          self.logger.message('Server not reachable yet (' + str(exc) + '), retrying for ' + str(wait_seconds) + 's',
            log.LOG_INFO)
        #
        await asyncio.sleep(2)
      #
    #
    await self.client.connect()
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

  def settings(self, section):
    # the plugin's section of pyseco.toml as dict
    return self.config.section(section)
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
      await self.accounts.player_seen(login, p.nickname, visit=True)
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

  async def player_chat(self, params):
    # /name args -> registered command; unknown commands are left alone (XAseco may know them)
    uid, login, text = params[0], params[1], params[2].strip()
    if uid == 0 or not text.startswith('/') or len(text) < 2:
      return
    #
    words = text[1:].split()
    player = self.players.get(login)
    ctx = commands.Context(commands.GAME, login, player.nickname if player else login,
      await self.accounts.role(login), words[1:], lambda reply: self.chat_to(login, reply))
    await self.commands.run(ctx, words[0])
  #

  async def chat_to(self, login, text):
    # server message only the player sees
    return await self.request(messages.Call('ChatSendServerMessageToLogin', '$fb0»$z$s ' + text, login))
  #

  async def call(self, method, *params):
    # any server method; unlike request() it raises the server's error (xmlrpc.client.Fault)
    return await self.client.send(messages.Call(method, *params))
  #

  def register_core_commands(self):
    self.commands.register('pyseco', self.cmd_help, help='lists the pyseco commands you can use',
      sources=(commands.GAME,))
    self.commands.register('help', self.cmd_help, help='lists the commands you can use', sources=(commands.DISCORD,))
    self.commands.register('staff', self.cmd_staff, role=accounts.OPERATOR, help='lists admins and operators')
    self.commands.register('setrole', self.cmd_setrole, role=accounts.MASTERADMIN,
      help='gives a player a role', usage='<login> <player|operator|admin>')
    self.commands.register('link', self.cmd_link, help='links your discord account (shows a code for !link)',
      sources=(commands.GAME,))
  #

  async def cmd_help(self, ctx):
    prefix = '/' if ctx.source == commands.GAME else '!'
    available = self.commands.available(ctx.role, ctx.source)
    lines = [prefix + c.name + (' ' + c.usage if c.usage else '') + ' - ' + c.help for c in available]
    if ctx.source == commands.GAME:
      # the game chat shows only a few lines at once, so one command per message
      for line in lines:
        await ctx.reply(line)
      #
    else:
      await ctx.reply('\n'.join(lines))
    #
  #

  async def cmd_staff(self, ctx):
    staff = await self.accounts.staff()
    if not staff:
      await ctx.reply('There are no admins or operators.')
      return
    #
    for login, nickname, role in staff:
      name = utilities.strip_colors(nickname) if nickname else login
      await ctx.reply(accounts.ROLE_NAMES[role] + ': ' + name + ' (' + login + ')')
    #
  #

  async def cmd_setrole(self, ctx):
    if len(ctx.args) != 2 or ctx.args[1].lower() not in accounts.ROLES_BY_NAME:
      raise commands.UsageError()
    #
    login, role = ctx.args[0], accounts.ROLES_BY_NAME[ctx.args[1].lower()]
    try:
      await self.accounts.set_role(login, role)
    except ValueError as exc:
      await ctx.reply(str(exc) + '.')
      return
    #
    await ctx.reply(login + ' is now ' + accounts.ROLE_NAMES[role] + '.')
  #

  async def cmd_link(self, ctx):
    code = self.accounts.create_link_code(ctx.login)
    await ctx.reply('Type $fff!link ' + code + '$z$s in the discord channel within 10 minutes to link your discord account.')
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
  parser.add_argument('--config', default='pyseco.toml',
    help='settings file (default: pyseco.toml); relative paths in it are relative to its directory')
  args = parser.parse_args()
  
  try:
    cfg = config.Config(args.config)
  except config.ConfigError as exc:
    print(exc, file=sys.stderr)
    return 1
  #
  logger = log.Logging(cfg.log_path, cfg.log_level)
  
  controller = TMController(cfg, logger)
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
