import asyncio
import configparser
import os

import discord

import log
from plugins.plugin import Plugin
import utilities


MAX_MESSAGE_LENGTH = 2000 # discord limit
MAX_QUEUED_MESSAGES = 200


def clean_name(name):
  # TM formatting codes removed, discord markdown (**, _, ...) neutralized
  return discord.utils.escape_markdown(utilities.strip_colors(name or ''))
#


class Discord(Plugin):
  # Mirrors the server chat and events to a discord channel and back.
  #
  # The discord client runs as a task in the same event loop as the controller, so no threads are needed.
  # Messages to discord go through a queue that a single sender task works off. That way the
  # server callbacks never wait for discord (rate limits can take seconds), the order is kept, and
  # messages arriving in a burst are combined into one discord message.

  def __init__(self, controller):
    super().__init__(controller)
    self.read_settings()

    self.client = DiscordClient(self)
    self.client_task = None
    self.sender_task = None
    self.channel = None
    self.ready = asyncio.Event() # set as soon as the channel is known
    self.outbox = asyncio.Queue(maxsize=MAX_QUEUED_MESSAGES)

    self.controller.register_event('TrackMania.PlayerChat', self.chat_to_dc)
    self.controller.register_event('PlayerConnectComplete', self.player_connect)
    self.controller.register_event('PlayerDisconnectComplete', self.player_disconnect)
    self.controller.register_event('TrackMania.BeginChallenge', self.new_challenge)
    self.controller.register_event('TrackMania.Echo', self.echo)

    # discord command -> (handler, admin only, description)
    self.commands = {
      'help': (self.dc_help, False, 'show this list'),
      'players': (self.dc_player_list, False, 'list the players on the server'),
      'admins': (self.dc_list_admins, False, 'list the bot admins'),
      'restart': (self.dc_restart, True, 'restart the current map'),
      'res': (self.dc_restart, True, None),
      'skip': (self.dc_skip, True, 'skip to the next map'),
      'next': (self.dc_skip, True, None),
    }
    if self.xaseco_path:
      self.commands['runxaseco'] = (self.dc_run_xaseco, True, 'start xaseco')
      self.commands['startxaseco'] = (self.dc_run_xaseco, True, None)
    #
  #

  def read_settings(self):
    settings_file = self.controller.plugin_settings_path('discord.ini')
    if not os.path.exists(settings_file):
      raise Exception('Missing settings file ' + settings_file + ' (see discord.ini.example)')
    #
    cfg = configparser.ConfigParser(interpolation=None) # '%' has no special meaning (tokens, passwords)
    cfg.read(settings_file, encoding='utf-8')
    if not cfg.has_section('discord'):
      raise Exception(settings_file + ' has no [discord] section (see discord.ini.example)')
    #
    s = cfg['discord']

    self.bot_token = s.get('bot_token', '').strip()
    channel_id = s.get('channel_id', '').strip()
    if not self.bot_token or not channel_id.isdigit():
      raise Exception('bot_token and channel_id must be set in ' + settings_file)
    #
    self.channel_id = int(channel_id)
    self.invite = s.get('dc_server_invite', '').strip()
    self.prefix = s.get('command_prefix', '!').strip() or '!'
    self.admins = [a.strip() for a in s.get('admins', '').split(',') if a.strip()]
    self.xaseco_path = s.get('xaseco_path', '').strip()
    self.xaseco_dir = s.get('xaseco_dir', '').strip() or None
  #

  async def start(self):
    self.sender_task = asyncio.create_task(self.sender())
    self.client_task = asyncio.create_task(self.client.start(self.bot_token))
    self.client_task.add_done_callback(self.client_stopped)
  #

  async def stop(self):
    if self.sender_task is not None:
      self.sender_task.cancel()
    #
    await self.client.close()
  #

  def client_stopped(self, task):
    # without this, a failed login (wrong token, missing intent, ...) would go unnoticed
    if task.cancelled():
      return
    #
    exc = task.exception()
    if exc is not None:
      self.log('Discord client stopped: ' + repr(exc), log.LOG_ERROR)
    #
  #

  def log(self, text, level=log.LOG_INFO):
    self.controller.logger.message('[discord] ' + text, level)
  #


  # ---- to discord ----

  def send(self, text):
    # only queues the message, never waits
    try:
      self.outbox.put_nowait(text)
    except asyncio.QueueFull:
      self.log('Message queue full, dropping message', log.LOG_WARNING)
    #
  #

  async def sender(self):
    pending = None
    while True:
      text = pending if pending is not None else await self.outbox.get()
      pending = None
      # combine what has piled up meanwhile, as long as it fits into one discord message
      while not self.outbox.empty():
        next_text = self.outbox.get_nowait()
        if len(text) + 1 + len(next_text) > MAX_MESSAGE_LENGTH:
          pending = next_text
          break
        #
        text += '\n' + next_text
      #

      await self.ready.wait()
      try:
        await self.channel.send(text[:MAX_MESSAGE_LENGTH])
      except discord.DiscordException as exc:
        self.log('Sending failed: ' + repr(exc), log.LOG_WARNING)
      #
    #
  #

  async def chat_to_dc(self, params):
    if params[0] == 0: # server's own messages
      return
    #
    if params[2].startswith('/'):
      return
    #

    login = params[1]
    player = await self.controller.get_player_by_login(login)
    self.send('**' + clean_name(player.nickname) + '** [' + discord.utils.escape_markdown(login) + ']: '
      + discord.utils.escape_markdown(params[2]))
  #

  async def player_connect(self, login):
    player = await self.controller.get_player_by_login(login)
    self.send('**' + clean_name(player.nickname) + '** [' + discord.utils.escape_markdown(login) + '] connected. ('
      + str(len(self.controller.players)) + ' online)')
  #

  async def player_disconnect(self, player):
    self.send('**' + clean_name(player.nickname) + '** [' + discord.utils.escape_markdown(player.login)
      + '] disconnected. (' + str(len(self.controller.players)) + ' online)')
  #

  async def new_challenge(self, params):
    map = params[0]
    self.send('Switching to map **' + clean_name(map['Name']) + '** by **' + clean_name(map['Author']) + '**')
  #

  async def echo(self, params):
    if len(params) != 2 or params[1] != 'xaseco::dedimania':
      return
    #
    vals = params[0].split('#', 2)
    if len(vals) < 3:
      return
    #
    place, time, login = vals
    player = await self.controller.get_player_by_login(login)
    self.send('**' + clean_name(player.nickname) + '** [' + discord.utils.escape_markdown(login)
      + '] gained Dedimania place **' + place + '** with a time of **' + time + '**')
  #


  # ---- from discord ----

  async def on_ready(self):
    channel = self.client.get_channel(self.channel_id)
    if channel is None:
      self.log('Channel ' + str(self.channel_id) + ' not found or not accessible for the bot', log.LOG_ERROR)
      return
    #
    self.channel = channel
    self.ready.set()
    self.log('Connected as ' + str(self.client.user) + ' to #' + channel.name)
  #

  async def on_message(self, message):
    if message.author == self.client.user or message.channel.id != self.channel_id:
      return
    #

    text = message.content
    if text.startswith(self.prefix):
      await self.run_command(message, text[len(self.prefix):].strip().lower())
      return
    #
    if not text: # e.g. only an attachment
      return
    #

    nick = message.author.display_name.replace('$', '$$')
    link = '$l[' + self.invite + ']discord$l' if self.invite else 'discord'
    await self.controller.chat_send_server_message('[' + nick + '@' + link + '] $z$s' + text)
  #

  async def run_command(self, message, name):
    if name not in self.commands:
      self.send('Unknown command. Type **' + self.prefix + 'help** for a list.')
      return
    #
    handler, admin_only, _ = self.commands[name]
    if admin_only and str(message.author.id) not in self.admins:
      self.send(message.author.mention + ' You do not have the required permissions for that action.')
      return
    #
    try:
      await handler(message)
    except Exception as exc:
      self.log('Command ' + name + ' failed: ' + repr(exc), log.LOG_ERROR)
      self.send('Command failed.')
    #
  #

  def discord_user_ingame(self, message):
    nick = message.author.display_name.replace('$', '$$')
    return nick + ('@$l[' + self.invite + ']discord$l' if self.invite else '@discord')
  #

  async def dc_help(self, message):
    lines = []
    for name, (_, admin_only, description) in self.commands.items():
      if description is not None:
        lines.append('**' + self.prefix + name + '** - ' + description + (' (admin)' if admin_only else ''))
      #
    #
    self.send('\n'.join(lines))
  #

  async def dc_player_list(self, message):
    players = await self.controller.get_player_list()
    if players is None:
      self.send('Could not get the player list from the server.')
      return
    #
    self.send(str(len(players)) + ' playing.')
    for player in players:
      self.send(clean_name(player['NickName']) + ' [' + discord.utils.escape_markdown(player['Login']) + ']')
    #
  #

  async def dc_list_admins(self, message):
    # mentions are shown, but don't ping anybody (allowed_mentions is none)
    self.send(' '.join('<@' + admin + '>' for admin in self.admins) or 'No admins configured.')
  #

  async def dc_skip(self, message):
    await self.controller.chat_send_server_message(self.discord_user_ingame(message) + ' skipped the map.')
    await self.controller.next_challenge()
  #

  async def dc_restart(self, message):
    await self.controller.chat_send_server_message(self.discord_user_ingame(message) + ' restarted the map.')
    await self.controller.restart()
  #

  async def dc_run_xaseco(self, message):
    await self.controller.chat_send_server_message(self.discord_user_ingame(message) + ' started xaseco.')
    await asyncio.create_subprocess_exec(self.xaseco_path, cwd=self.xaseco_dir)
    self.send('XAseco started.')
  #
#


class DiscordClient(discord.Client):

  def __init__(self, plugin):
    intents = discord.Intents.default()
    intents.message_content = True # privileged, must also be enabled in the discord developer portal
    # never ping anyone, whatever players write in the game chat (@everyone, ...)
    super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
    self.plugin = plugin
  #

  async def on_ready(self):
    await self.plugin.on_ready()
  #

  async def on_message(self, message):
    await self.plugin.on_message(message)
  #
#
