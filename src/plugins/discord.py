import asyncio

import discord

from core import commands, events, log, roles
from core.text import strip_colors
from plugins.plugin import Plugin
from services import ui
from services.rankings import difference, ordinal, race_time
from services.windows import ROW_STYLE


MAX_MESSAGE_LENGTH = 2000 # discord limit
MAX_QUEUED_MESSAGES = 200


def clean_name(name):
  # TM formatting codes removed, discord markdown (**, _, ...) neutralized
  return discord.utils.escape_markdown(strip_colors(name or ''))
#


class Discord(Plugin):
  # Mirrors the server chat and events to a discord channel and back.
  #
  # The discord client runs as a task in the same event loop as the controller, so no threads are needed.
  # Messages to discord go through a queue that a single sender task works off. That way the
  # server callbacks never wait for discord (rate limits can take seconds), the order is kept, and
  # messages arriving in a burst are combined into one discord message.
  #
  # Commands (!name) are the controller's commands available on discord. Their permissions come from
  # the TM login a discord account is linked to (/link in game, then !link <code> here).
  #
  # Settings ([discord] in pyseco.toml):
  #   token = "..."              bot token
  #   channel_id = 123           channel mirrored with the server chat
  #   invite = "discord.gg/..."  shown in game next to discord names and as a button (optional)
  #   button = true              the button that opens the invite (the widget "discord", [widgets.discord] moves it);
  #                              the Discord logo with pyseco's web server ([http]), otherwise a text button
  #   prefix = "!"               command prefix (optional)
  #   local_records = 0          new local records up to this rank are posted (0: none)
  #   dedimania = 30             the same for Dedimania records
  #
  # A command that does not answer by itself (e.g. one that only tells the game) gets a short "done".

  def __init__(self, controller):
    super().__init__(controller)
    settings = controller.settings('discord')
    self.bot_token = str(settings.get('token', '')).strip()
    self.channel_id = settings.get('channel_id')
    if not self.bot_token or not isinstance(self.channel_id, int):
      raise Exception('token and channel_id (a number) must be set in the [discord] section of pyseco.toml')
    #
    self.invite = str(settings.get('invite', '')).strip()
    self.button = bool(settings.get('button', True)) and bool(self.invite)
    self.button_id = controller.ui.manialink_id()
    # below the game's ranking box at the top left
    self.button_x, self.button_y = controller.ui.position('discord', -64, 27.8) # lined up with that box
    self.prefix = str(settings.get('prefix', '!')).strip() or '!'
    self.record_ranks = {'local': int(settings.get('local_records', 0)), 'dedimania': int(settings.get('dedimania', 30))}
    self.record_names = {'local': 'local', 'dedimania': 'Dedimania'}

    self.client = DiscordClient(self)
    self.client_task = None
    self.sender_task = None
    self.channel = None
    self.ready = asyncio.Event() # set as soon as the channel is known
    self.outbox = asyncio.Queue(maxsize=MAX_QUEUED_MESSAGES)

    controller.events.register(events.CHAT, self.chat_to_dc)
    controller.events.register(events.PLAYER_JOINED, self.player_connect)
    controller.events.register(events.PLAYER_LEFT, self.player_disconnect)
    controller.events.register(events.MAP_STARTED, self.new_challenge)
    controller.events.register(events.RECORD, self.record)

    register = controller.commands.register
    only_discord = (commands.DISCORD,)
    register('help', self.cmd_help, help='lists the commands you can use', sources=only_discord)
    register('players', self.cmd_players, help='lists the players on the server', sources=only_discord)
    register('link', self.cmd_link, help='links your discord account to your TM login (get the code with /link in game)',
      usage='<code>', sources=only_discord)
    register('link', self.cmd_link_code, help='links your discord account (shows a code for !link)',
      sources=(commands.GAME,))
    register('unlink', self.cmd_unlink, help='removes the link to your TM login', sources=only_discord)
    register('whoami', self.cmd_whoami, help='shows your linked TM login and role', sources=only_discord)
  #

  async def start(self):
    if self.button:
      await self.show_button()
    #
    self.sender_task = asyncio.create_task(self.sender())
    self.client_task = asyncio.create_task(self.client.start(self.bot_token))
    self.client_task.add_done_callback(self.client_stopped)
  #

  async def stop(self):
    if self.sender_task is not None:
      self.sender_task.cancel()
    #
    if self.button:
      await self.controller.ui.hide(self.button_id)
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

  def player_name(self, player):
    return '**' + clean_name(player.nickname) + '** [' + discord.utils.escape_markdown(player.login) + ']'
  #

  async def chat_to_dc(self, message):
    self.send(self.player_name(message.player) + ': ' + discord.utils.escape_markdown(message.text))
  #

  async def show_button(self, login=None):
    # a small button that opens the invite link: the Discord logo, or text without web server
    logo = self.controller.web.url('discord.png')
    if logo:
      # the logo (619 x 470 pixels) on a light button (chosen in game); a unit is about 15 pixels wide but only 11 high
      button = ui.quad(0, 0, 0, 4.8, 4.6, 'Bgs1InRace', 'BgButton', url=self.invite) \
        + ui.quad(0.8, -0.67, 1, 3.2, 3.26, image=logo, url=self.invite)
    else:
      button = ui.quad(0, 0, 0, 7, 2, *ROW_STYLE, url=self.invite) \
        + ui.label(3.5, -1, 1, '$fffDiscord', 6.4, 1.6, size=1, halign='center', valign='center')
    #
    await self.controller.ui.show(self.button_id, ui.frame(button, self.button_x, self.button_y, 10), login)
  #

  async def player_connect(self, player):
    if self.button:
      await self.show_button(player.login)
    #
    self.send(self.player_name(player) + ' connected. (' + str(self.controller.players.count()) + ' online)')
  #

  async def player_disconnect(self, player):
    self.send(self.player_name(player) + ' disconnected. (' + str(self.controller.players.count()) + ' online)')
  #

  async def record(self, record):
    if record.rank > self.record_ranks.get(record.kind, 0):
      return
    #
    gain = ' (-' + difference(record.old_time - record.time) + ')' if record.old_time is not None else ''
    self.send('\N{CHEQUERED FLAG} ' + self.player_name(record.player) + (' improved to' if record.old_time else ' drove')
      + ' the **' + ordinal(record.rank) + '** ' + self.record_names.get(record.kind, record.kind) + ' record on **'
      + clean_name(record.map['Name']) + '**: **' + race_time(record.time) + '**' + gain)
  #

  async def new_challenge(self, map):
    self.send('Switching to map **' + clean_name(map['Name']) + '** by **' + clean_name(map['Author']) + '**')
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
      await self.run_command(message, text[len(self.prefix):].strip())
      return
    #
    if not text: # e.g. only an attachment
      return
    #

    nick = message.author.display_name.replace('$', '$$')
    link = ui.link(self.invite, 'discord') if self.invite else 'discord'
    await self.controller.chat.send_raw('[' + nick + '@' + link + '] $z$s' + text)
  #

  async def run_command(self, message, text):
    words = text.split()
    if not words:
      return
    #
    login = await self.controller.accounts.login_for_discord(message.author.id)
    role = await self.controller.accounts.role(login) if login else roles.PLAYER
    replied = []
    async def reply(text):
      replied.append(text)
      await self.reply(text)
    #
    ctx = commands.Context(commands.DISCORD, login, message.author.display_name, role, words[1:], reply,
      discord_id=message.author.id)
    if not await self.controller.commands.run(ctx, words[0]):
      self.send('Unknown command. Type **' + self.prefix + 'help** for a list.')
    elif not replied:
      # the command only told the game (or nothing): the sender should know it worked
      self.send('\N{WHITE HEAVY CHECK MARK} ' + discord.utils.escape_markdown(self.prefix + text) + ' - done.')
    #
  #

  async def reply(self, text):
    # command answers may contain TM formatting (nicknames), discord shows them plain
    self.send(strip_colors(text))
  #

  async def cmd_help(self, ctx):
    lines = [self.prefix + c.name + (' ' + c.usage if c.usage else '') + ' - ' + c.help
      for c in self.controller.commands.available(ctx.role, commands.DISCORD)]
    await ctx.reply('\n'.join(lines))
  #

  async def cmd_players(self, ctx):
    players = await self.controller.server.get_player_list(300, 0)
    lines = [str(len(players)) + ' playing.']
    lines += [clean_name(p['NickName']) + ' [' + discord.utils.escape_markdown(p['Login']) + ']' for p in players]
    await ctx.reply('\n'.join(lines))
  #

  async def cmd_link(self, ctx):
    if len(ctx.args) != 1:
      raise commands.UsageError()
    #
    login = await self.controller.accounts.redeem_link_code(ctx.args[0], ctx.discord_id)
    if login is None:
      await ctx.reply('Unknown or expired code. Type /link in game to get a new one.')
      return
    #
    role = await self.controller.accounts.role(login)
    await ctx.reply('Linked to ' + login + ' (' + roles.NAMES[role] + ').')
  #

  async def cmd_link_code(self, ctx):
    # in game: the code to type on discord
    code = self.controller.accounts.create_link_code(ctx.login)
    await ctx.reply('Type $fff' + self.prefix + 'link ' + code + '$z$s in the discord channel within 10 minutes to link '
      'your discord account.')
  #

  async def cmd_unlink(self, ctx):
    if await self.controller.accounts.unlink_discord(ctx.discord_id):
      await ctx.reply('Link removed.')
    else:
      await ctx.reply('Your discord account is not linked.')
    #
  #

  async def cmd_whoami(self, ctx):
    if ctx.login is None:
      await ctx.reply('Not linked. Type /link in game to get a code, then !link <code> here.')
    else:
      await ctx.reply('Linked to ' + ctx.login + ' (' + roles.NAMES[ctx.role] + ').')
    #
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
