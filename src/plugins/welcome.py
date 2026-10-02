from core import events, roles
from plugins.plugin import Plugin


DEFAULTS = {
  'message': 'Welcome {nickname}$z$s to {server}$z$s! Type $fff/pyseco$z$s for the commands.',
  'join': '{nickname}$z$s joined the server ({visits_text}).',
  'leave': '{nickname}$z$s left the server.',
}


class Template(dict):
  # format_map values: unknown placeholders stay as they are, so a typo shows up instead of failing
  def __missing__(self, key):
    return '{' + key + '}'
  #
#


class Welcome(Plugin):
  # Greets players when they join and tells everybody who comes and goes.
  #
  # Settings ([welcome] in pyseco.toml), "" switches a message off:
  #   message = "..."  to the player who joined
  #   join = "..."     to everybody when a player joins
  #   leave = "..."    to everybody when a player leaves
  # Placeholders: {nickname} {login} {role} {visits} (number of visits) {visits_text} ("first visit", "visit 3")
  # {server} (server name)

  def __init__(self, controller):
    super().__init__(controller)
    settings = controller.settings('welcome')
    self.texts = {key: str(settings.get(key, default)) for key, default in DEFAULTS.items()}
    self.server_name = ''
    controller.events.register(events.PLAYER_JOINED, self.player_joined)
    controller.events.register(events.PLAYER_LEFT, self.player_left)
  #

  async def start(self):
    self.server_name = await self.controller.server.get_server_name()
  #

  async def values(self, player):
    stored = await self.controller.storage.players.get(player.login)
    visits = stored.visits if stored else 1
    return Template(nickname=player.nickname, login=player.login, server=self.server_name, visits=visits,
      visits_text='first visit' if visits <= 1 else 'visit ' + str(visits),
      role=roles.NAMES[await self.controller.accounts.role(player.login)])
  #

  async def player_joined(self, player):
    values = await self.values(player)
    if self.texts['message']:
      await self.controller.chat.tell(player.login, self.texts['message'].format_map(values))
    #
    if self.texts['join']:
      await self.controller.chat.announce(self.texts['join'].format_map(values))
    #
  #

  async def player_left(self, player):
    if self.texts['leave']:
      await self.controller.chat.announce(self.texts['leave'].format_map(await self.values(player)))
    #
  #
#
