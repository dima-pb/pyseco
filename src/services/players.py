import xmlrpc.client

from core import commands, events, roles
from core.text import strip_colors


MAX_PLAYERS = 300


class Player:
  # a player on the server right now

  def __init__(self, login, is_spec=False):
    self.login = login
    self.nickname = login
    self.id = None # PlayerId on the server, set once the server sent the player's info
    self.team_id = None
    self.is_spec = is_spec
    self.ladder_rank = None
    self.flags = None # see server_api.PlayerInfo
  #

  def update(self, info):
    # info: server_api.PlayerInfo
    self.nickname = info['NickName']
    self.id = info['PlayerId']
    self.team_id = info['TeamId']
    if 'SpectatorStatus' in info:
      self.is_spec = info['SpectatorStatus'] % 10 != 0
    elif 'IsSpectator' in info:
      self.is_spec = info['IsSpectator']
    #
    self.ladder_rank = info['LadderRanking']
    self.flags = info.get('Flags')
  #
#


class Players:
  # Who is on the server (online), and the commands around players and their roles.
  # Roles and discord links are kept by controller.accounts.

  def __init__(self, controller):
    self.controller = controller
    self.online = {} # login -> Player
    controller.events.register('TrackMania.PlayerConnect', self.player_connect)
    controller.events.register('TrackMania.PlayerDisconnect', self.player_disconnect)
    controller.events.register('TrackMania.PlayerInfoChanged', self.player_info_changed)

    register = controller.commands.register
    register('staff', self.cmd_staff, role=roles.OPERATOR, help='lists admins and operators')
    register('setrole', self.cmd_setrole, role=roles.MASTERADMIN, help='gives a player a role',
      usage='<login> <player|operator|admin>')
  #

  async def start(self):
    for info in await self.controller.server.get_player_list(MAX_PLAYERS, 0):
      await self.update(info)
    #
  #

  def count(self):
    return len(self.online)
  #

  def find(self, text):
    # online players by login, or by a part of login or nickname (without colors), case does not matter;
    # an exact login wins: [Player], empty if nobody matches
    if text in self.online:
      return [self.online[text]]
    #
    text = text.lower()
    return [p for p in self.online.values() if text in p.login.lower() or text in strip_colors(p.nickname).lower()]
  #

  async def get(self, login):
    # the online player; asks the server if pyseco doesn't know the player (yet), None if not on the server
    player = self.online.get(login)
    if player is None or player.id is None:
      try:
        await self.update(await self.controller.server.get_player_info(login))
      except xmlrpc.client.Fault:
        return player
      #
      player = self.online.get(login)
    #
    return player
  #

  async def update(self, info):
    login = info['Login']
    player = self.online.get(login)
    if player is None:
      player = self.online[login] = Player(login)
    #
    just_joined = player.id is None
    player.update(info)
    if just_joined and player.id is not None:
      await self.controller.accounts.player_seen(login, player.nickname, visit=True)
      await self.controller.events.emit(events.PLAYER_JOINED, player)
    #
  #

  async def player_connect(self, params):
    login, is_spec = params[0], params[1]
    self.online[login] = Player(login, is_spec) # complete with PlayerInfoChanged
  #

  async def player_disconnect(self, params):
    player = self.online.pop(params[0], None)
    if player is not None:
      await self.controller.events.emit(events.PLAYER_LEFT, player)
    #
  #

  async def player_info_changed(self, params):
    await self.update(params[0])
  #


  # ---- commands ----

  async def cmd_staff(self, ctx):
    staff = await self.controller.accounts.staff()
    if not staff:
      await ctx.reply('There are no admins or operators.')
      return
    #
    for login, nickname, role in staff:
      name = strip_colors(nickname) if nickname else login
      await ctx.reply(roles.NAMES[role] + ': ' + name + ' (' + login + ')')
    #
  #

  async def cmd_setrole(self, ctx):
    if len(ctx.args) != 2 or ctx.args[1].lower() not in roles.BY_NAME:
      raise commands.UsageError()
    #
    login, role = ctx.args[0], roles.BY_NAME[ctx.args[1].lower()]
    try:
      await self.controller.accounts.set_role(login, role)
    except ValueError as exc:
      await ctx.reply(str(exc) + '.')
      return
    #
    await ctx.reply(login + ' is now ' + roles.NAMES[role] + '.')
    await self.controller.events.emit(events.ROLE_CHANGED, login)
  #
#
