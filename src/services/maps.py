import xmlrpc.client

from core import commands, events, log, roles
from core.text import strip_colors


MAX_MAPS = 5000


class Maps:
  # The server's map list, the current map and which maps were played when.
  # Maps are the server's dicts, see core.server_api.ChallengeInfo.
  #
  # Settings ([maps] in pyseco.toml):
  #   matchsettings = "MatchSettings/active.txt"   the server's match settings file (relative to its Tracks
  #                   directory); changes of the map list are saved there. Without it they last until the
  #                   server restarts

  def __init__(self, controller):
    self.controller = controller
    self.matchsettings = str(controller.settings('maps').get('matchsettings', '')).strip()
    self.list = [] # in the server's order
    self.by_uid = {}
    self.current = None
    controller.admin.register('remove', self.cmd_remove, role=roles.ADMIN, usage='[<number in /list>]',
      help='removes the current map (or that one) from the map list')
    controller.admin.register('save', self.cmd_save, role=roles.ADMIN, help='saves the map list in the match settings')
    controller.events.register('TrackMania.BeginChallenge', self.begin_challenge)
    controller.events.register('TrackMania.ChallengeListModified', self.list_modified)
    controller.events.register('TrackMania.EndChallenge', self.end_challenge)
  #

  async def start(self):
    # while the server is still loading it has no map yet: BeginChallenge / ChallengeListModified will tell
    try:
      await self.refresh()
      self.current = await self.controller.server.get_current_challenge_info()
    except xmlrpc.client.Fault as fault:
      self.controller.logger.message('Map list not available yet: ' + fault.faultString, log.LOG_INFO)
    #
  #

  async def refresh(self):
    self.list = await self.controller.server.get_challenge_list(MAX_MAPS, 0)
    self.by_uid = {m['UId']: m for m in self.list}
    await self.controller.storage.maps.known(self.list)
  #

  async def list_modified(self, params):
    if params[2]: # IsListModified
      await self.refresh()
      await self.controller.events.emit(events.MAP_LIST_CHANGED)
    #
  #

  async def begin_challenge(self, params):
    if not self.list:
      await self.refresh()
    #
    self.current = params[0]
    await self.controller.storage.maps.known([self.current])
    await self.controller.storage.maps.played(self.current['UId'])
    await self.controller.events.emit(events.MAP_STARTED, self.current)
  #

  async def end_challenge(self, params):
    # params: rankings, map, was warm-up, match continues, restart
    await self.controller.events.emit(events.MAP_ENDED, params[1])
  #

  async def save(self):
    # the map list into the match settings file; False if there is none configured
    if not self.matchsettings:
      return False
    #
    await self.controller.server.save_match_settings(self.matchsettings)
    return True
  #

  async def remove(self, uid):
    # takes the map off the server's list (the file stays) and saves the list; True if it was saved
    await self.controller.server.remove_challenge(self.by_uid[uid]['FileName'])
    await self.refresh()
    return await self.save()
  #

  async def cmd_remove(self, ctx):
    if len(ctx.args) > 1 or (ctx.args and not ctx.args[0].isdigit()):
      raise commands.UsageError()
    #
    if ctx.args:
      number = int(ctx.args[0])
      if not 1 <= number <= len(self.list):
        await ctx.reply('There is no map ' + ctx.args[0] + ', see /list.')
        return
      #
      m = self.list[number - 1]
    elif self.current is not None and self.current['UId'] in self.by_uid:
      m = self.current
    else:
      await ctx.reply('The current map is not in the map list.')
      return
    #
    if len(self.list) == 1:
      await ctx.reply('This is the last map, the server needs at least one.')
      return
    #
    try:
      saved = await self.remove(m['UId'])
    except xmlrpc.client.Fault as fault:
      await ctx.reply('The server did not remove the map: ' + fault.faultString)
      return
    #
    self.controller.logger.message('[maps] ' + str(ctx.login) + ' removed ' + m['FileName'], log.LOG_INFO)
    await self.controller.chat.announce(self.controller.admin.who(ctx) + ' removed $fff' + strip_colors(m['Name'])
      + '$z$s from the map list.')
    if not saved:
      await ctx.reply('Not saved: [maps] matchsettings is not set, the map comes back when the server restarts.')
    #
  #

  async def cmd_save(self, ctx):
    if await self.save():
      await ctx.reply('The map list is saved in ' + self.matchsettings + '.')
    else:
      await ctx.reply('[maps] matchsettings is not set in pyseco.toml.')
    #
  #

  async def history(self, count):
    # the most recently started maps, newest first (the current one included): [(uid, name, played_at)]
    return [(p.uid, p.name, p.played_at) for p in await self.controller.storage.maps.history(count)]
  #

  async def recent_uids(self, count):
    # uids of the last maps played, without the current one
    return [uid for uid, _, _ in (await self.history(count + 1))[1:]]
  #

  def index_of(self, uid):
    for i, m in enumerate(self.list):
      if m['UId'] == uid:
        return i
      #
    #
    return None
  #
#
