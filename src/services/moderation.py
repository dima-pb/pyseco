import datetime
import re
import xmlrpc.client

from core import commands, events, log, roles
from core.text import strip_colors
from services.windows import ListWindow


DURATION = re.compile(r'^(\d+)([mhd])$')
UNITS = {'m': 'minutes', 'h': 'hours', 'd': 'days'}
WINDOW_BANS = [('Ban for 1 day', '1d'), ('Ban for 7 days', '7d'), ('Ban for ever', None)]


def ban_until(duration):
  # '30m', '2h', '7d' -> 'YYYY-MM-DD HH:MM:SS' (UTC) as the storage keeps it; None -> None (for ever)
  if duration is None:
    return None
  #
  number, unit = DURATION.match(duration).groups()
  until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(**{UNITS[unit]: int(number)})
  return until.strftime('%Y-%m-%d %H:%M:%S')
#


def describe_until(until):
  return 'for ever' if until is None else 'until ' + until[:16] + ' UTC'
#


class Actor:
  # who does something: from a command or from a click in a window
  def __init__(self, login, name, role):
    self.login = login
    self.name = name
    self.role = role
  #
#


class Moderation:
  # Kick, mute and ban, and the list of players. Bans and mutes are kept in storage and enforced whenever
  # a player connects (pyseco's own lists, the server's ban and black lists are not used). Nobody can act on
  # a player with the same or a higher role.

  def __init__(self, controller):
    self.controller = controller
    self.store = controller.storage.moderation
    self.players_window = ListWindow(controller.ui, width=90, columns=[44, 28, 14])
    self.actions_window = ListWindow(controller.ui, width=50, page_size=6)
    self.bans_window = ListWindow(controller.ui, width=120, columns=[24, 28, 20, 44])
    controller.events.register('TrackMania.PlayerConnect', self.player_connect)
    controller.events.register(events.PLAYER_JOINED, self.player_joined)

    register = controller.commands.register
    register('players', self.cmd_players, help='lists the players on the server', sources=(commands.GAME,))
    register('kick', self.cmd_kick, role=roles.OPERATOR, help='kicks a player from the server',
      usage='<player> [reason]')
    register('mute', self.cmd_mute, role=roles.OPERATOR, help='nobody sees the chat of the player any more',
      usage='<player>')
    register('unmute', self.cmd_unmute, role=roles.OPERATOR, help='the player can chat again', usage='<login>')
    register('ban', self.cmd_ban, role=roles.ADMIN, help='bans a player, for ever or for a time (30m, 2h, 7d)',
      usage='<player> [time] [reason]')
    register('unban', self.cmd_unban, role=roles.ADMIN, help='lifts a ban', usage='<login>')
    register('bans', self.cmd_bans, role=roles.ADMIN, help='lists the banned players')
  #

  async def start(self):
    muted = await self.store.muted()
    for login in list(self.controller.players.online):
      if login in muted:
        await self.ignore(login, True)
      #
    #
  #

  def log(self, text):
    self.controller.logger.message('[moderation] ' + text, log.LOG_INFO)
  #


  # ---- enforcing ----

  async def player_connect(self, params):
    login = params[0]
    ban = await self.store.ban_of(login)
    if ban is not None:
      self.log(login + ' is banned, kicked')
      await self.server_kick(login, 'You are banned from this server ' + describe_until(ban.until)
        + (': ' + ban.reason if ban.reason else '') + '.')
    #
  #

  async def player_joined(self, player):
    if player.login in await self.store.muted():
      await self.ignore(player.login, True)
    #
  #

  async def server_kick(self, login, message):
    try:
      await self.controller.server.kick(login, message)
    except xmlrpc.client.Fault as fault:
      self.log('Could not kick ' + login + ': ' + fault.faultString)
    #
  #

  async def ignore(self, login, on):
    # the server's ignore list: chat of these players is not passed on
    try:
      if on:
        await self.controller.server.ignore(login)
      else:
        await self.controller.server.un_ignore(login)
      #
    except xmlrpc.client.Fault as fault:
      self.log(('Ignore ' if on else 'UnIgnore ') + login + ': ' + fault.faultString)
    #
  #


  # ---- actions, used by commands and windows ----

  async def name_of(self, login):
    player = self.controller.players.online.get(login)
    if player is not None:
      return player.nickname
    #
    stored = await self.controller.storage.players.get(login)
    return stored.nickname if stored and stored.nickname else login
  #

  async def allowed(self, actor, login, reply):
    if login == actor.login:
      await reply('You can\'t do that to yourself.')
      return False
    #
    if await self.controller.accounts.role(login) >= actor.role:
      await reply('You can\'t do that to ' + login + ', their role is not below yours.')
      return False
    #
    return True
  #

  async def kick(self, actor, login, reason, reply):
    if not await self.allowed(actor, login, reply):
      return
    #
    name = await self.name_of(login)
    await self.server_kick(login, 'You were kicked by ' + strip_colors(actor.name) + (': ' + reason if reason else '.'))
    self.log(actor.login + ' kicked ' + login + (': ' + reason if reason else ''))
    await self.controller.chat.announce('$fff' + actor.name + '$z$s kicked $fff' + name + '$z$s'
      + ('$z$s: ' + reason if reason else '.'))
  #

  async def mute(self, actor, login, reply):
    if not await self.allowed(actor, login, reply):
      return
    #
    await self.store.mute(login, actor.login)
    if login in self.controller.players.online:
      await self.ignore(login, True)
    #
    self.log(actor.login + ' muted ' + login)
    await self.controller.chat.announce('$fff' + actor.name + '$z$s muted $fff' + await self.name_of(login) + '$z$s.')
  #

  async def unmute(self, actor, login, reply):
    if not await self.store.unmute(login):
      await reply(login + ' is not muted.')
      return
    #
    if login in self.controller.players.online:
      await self.ignore(login, False)
    #
    self.log(actor.login + ' unmuted ' + login)
    await self.controller.chat.announce('$fff' + actor.name + '$z$s unmuted $fff' + await self.name_of(login) + '$z$s.')
  #

  async def ban(self, actor, login, duration, reason, reply):
    if not await self.allowed(actor, login, reply):
      return
    #
    until = ban_until(duration)
    name = await self.name_of(login)
    await self.store.ban(login, reason, actor.login, until)
    if login in self.controller.players.online:
      await self.server_kick(login, 'You were banned ' + describe_until(until) + (': ' + reason if reason else '.'))
    #
    self.log(actor.login + ' banned ' + login + ' ' + describe_until(until) + (': ' + reason if reason else ''))
    await self.controller.chat.announce('$fff' + actor.name + '$z$s banned $fff' + name + '$z$s ' + describe_until(until)
      + ('$z$s: ' + reason if reason else '.'))
  #


  # ---- commands ----

  async def target(self, ctx, offline=False):
    # the player the command is about (first argument): login, or None after telling why
    if not ctx.args:
      raise commands.UsageError()
    #
    matches = self.controller.players.find(ctx.args[0])
    if len(matches) == 1:
      return matches[0].login
    #
    if len(matches) > 1:
      await ctx.reply('Several players match "' + ctx.args[0] + '": ' + ', '.join(sorted(p.login for p in matches)) + '.')
      return None
    #
    if offline:
      return ctx.args[0] # a login of somebody who is not on the server
    #
    await ctx.reply('No player on the server matches "' + ctx.args[0] + '".')
    return None
  #

  def actor(self, ctx):
    return Actor(ctx.login, ctx.display_name, ctx.role)
  #

  async def cmd_kick(self, ctx):
    login = await self.target(ctx)
    if login is not None:
      await self.kick(self.actor(ctx), login, ' '.join(ctx.args[1:]), ctx.reply)
    #
  #

  async def cmd_mute(self, ctx):
    login = await self.target(ctx, offline=True)
    if login is not None:
      await self.mute(self.actor(ctx), login, ctx.reply)
    #
  #

  async def cmd_unmute(self, ctx):
    if len(ctx.args) != 1:
      raise commands.UsageError()
    #
    await self.unmute(self.actor(ctx), ctx.args[0], ctx.reply)
  #

  async def cmd_ban(self, ctx):
    login = await self.target(ctx, offline=True)
    if login is None:
      return
    #
    rest = ctx.args[1:]
    duration = rest.pop(0).lower() if rest and DURATION.match(rest[0].lower()) else None
    await self.ban(self.actor(ctx), login, duration, ' '.join(rest), ctx.reply)
  #

  async def cmd_unban(self, ctx):
    if len(ctx.args) != 1:
      raise commands.UsageError()
    #
    if await self.store.unban(ctx.args[0]):
      self.log(ctx.login + ' unbanned ' + ctx.args[0])
      await ctx.reply(ctx.args[0] + ' is no longer banned.')
    else:
      await ctx.reply(ctx.args[0] + ' is not banned.')
    #
  #

  async def cmd_bans(self, ctx):
    bans = await self.store.bans()
    if ctx.source == commands.GAME:
      rows = [('$fff' + b.login, '$ddd' + describe_until(b.until), '$ddd' + b.by, '$ddd' + b.reason) for b in bans]
      await self.bans_window.open(ctx.login, 'Banned players', rows, hint='/unban <login> lifts a ban')
    elif not bans:
      await ctx.reply('Nobody is banned.')
    else:
      await ctx.reply('\n'.join(b.login + ' ' + describe_until(b.until) + ' by ' + b.by + (': ' + b.reason if b.reason else '')
        for b in bans))
    #
  #

  async def cmd_players(self, ctx):
    online = sorted(self.controller.players.online.values(), key=lambda p: strip_colors(p.nickname).lower())
    muted = await self.store.muted()
    rows = []
    for p in online:
      role = await self.controller.accounts.role(p.login)
      rows.append(('$fff' + p.nickname, '$ddd' + p.login, '$ddd' + (roles.NAMES[role] if role else '')
        + (' muted' if p.login in muted else '')))
    #
    logins = [p.login for p in online]
    async def actions(login, index):
      await self.open_actions(login, logins[index])
    #
    staff = ctx.role >= roles.OPERATOR
    await self.players_window.open(ctx.login, 'Players (' + str(len(online)) + ')', rows, actions if staff else None,
      hint='Click a player for kick, mute, ban' if staff else '')
  #

  async def open_actions(self, login, target):
    if target not in self.controller.players.online:
      await self.controller.chat.tell(login, target + ' is no longer on the server.')
      return
    #
    role = await self.controller.accounts.role(login)
    muted = target in await self.store.muted()
    choices = [('Kick', None), ('Unmute' if muted else 'Mute', None)]
    if role >= roles.ADMIN:
      choices += WINDOW_BANS
    #
    async def chosen(login, index):
      await self.actions_window.close(login)
      reply = lambda text: self.controller.chat.tell(login, text)
      player = self.controller.players.online.get(login)
      actor = Actor(login, player.nickname if player else login, await self.controller.accounts.role(login))
      label, duration = choices[index]
      if label == 'Kick':
        await self.kick(actor, target, '', reply)
      elif label == 'Mute':
        await self.mute(actor, target, reply)
      elif label == 'Unmute':
        await self.unmute(actor, target, reply)
      else:
        await self.ban(actor, target, duration, '', reply)
      #
    #
    await self.actions_window.open(login, self.controller.players.online[target].nickname,
      ['$fff' + label for label, _ in choices], chosen)
  #
#
