import xmlrpc.client

from core import commands, events, log, roles
from core.text import strip_colors
from services.windows import ListWindow


HISTORY = 30 # maps /history shows


class PlaylistError(Exception):
  # a request the playlist can't take; the message tells the requester why
  pass
#


class Entry:
  # one requested map; source: Jukebox, Replay, TMX, Admin, ...; login/nickname of who asked for it

  def __init__(self, uid, filename, name, environment='', login='', nickname='', source='Jukebox'):
    self.uid = uid
    self.filename = filename
    self.name = name
    self.environment = environment
    self.login = login
    self.nickname = nickname
    self.source = source
  #

  @staticmethod
  def from_map(m, login='', nickname='', source='Jukebox'):
    # m: server_api.ChallengeInfo
    return Entry(m['UId'], m['FileName'], m['Name'], m.get('Environnement', ''), login, nickname, source)
  #

  def requested_by(self):
    return strip_colors(self.nickname) or self.source
  #
#


class Playlist:
  # Decides which map comes next. Requests (from the jukebox, votes, TMX, admins) are queued; the first one
  # is set as the server's next map right away, so skips and votes work too. Without requests the server
  # plays its map list in order.
  # Temporary maps (e.g. from TMX) are added to the server for the request and removed after they were
  # played, unless an admin keeps them with /addthis.

  def __init__(self, controller):
    self.controller = controller
    self.store = controller.storage.playlist
    self.queue = [] # [Entry], stored as QueuedMap (same fields)
    self.temporary = {} # uid -> filename of maps to remove after they were played
    self.playing_temporary = None # uid of the temporary map being played
    self.next_window = ListWindow(controller.ui, width=90, columns=[7, 50, 29])
    self.history_window = ListWindow(controller.ui, width=90, columns=[7, 56, 23])

    controller.events.register(events.MAP_STARTED, self.map_started)
    controller.events.register(events.MAP_LIST_CHANGED, self.list_changed)

    register = controller.commands.register
    register('nextmap', self.cmd_nextmap, help='shows the next map')
    register('history', self.cmd_history, help='shows the recently played maps')
    register('addthis', self.cmd_addthis, role=roles.ADMIN, help='keeps the current temporary (TMX) map on the server')
    admin = controller.admin
    admin.register('next', self.cmd_next, role=roles.OPERATOR, help='goes to the next map now')
    admin.register('restart', self.cmd_restart, role=roles.OPERATOR, help='restarts the current map now')
    admin.register('replay', self.cmd_replay, role=roles.OPERATOR, help='plays the current map again after this one')
  #

  async def start(self):
    self.queue = [Entry(q.uid, q.filename, q.name, q.environment, q.login, q.nickname, q.source)
      for q in await self.store.queue()]
    self.temporary = await self.store.temporary_maps()
    current = self.controller.maps.current
    if current is not None and current['UId'] in self.temporary:
      self.playing_temporary = current['UId']
    #
    await self.apply_next()
  #

  def log(self, text, level=log.LOG_INFO):
    self.controller.logger.message('[playlist] ' + text, level)
  #


  # ---- requests ----

  async def request(self, entry, front=False, temporary=False):
    # queues the map (first with front=True); temporary: a file that is not on the server yet, added for this
    # request and removed after it was played. Raises PlaylistError if the map can't be queued.
    if any(e.uid == entry.uid for e in self.queue):
      raise PlaylistError('This map is already in the queue.')
    #
    server = self.controller.server
    if entry.uid not in self.controller.maps.by_uid:
      try:
        await server.add_challenge(entry.filename)
      except xmlrpc.client.Fault as fault:
        raise PlaylistError('The server did not accept the map: ' + fault.faultString) from None
      #
      await self.controller.maps.refresh()
    #
    try:
      await server.check_challenge_for_current_server_params(entry.filename)
    except xmlrpc.client.Fault as fault:
      raise PlaylistError('The map does not fit the server settings: ' + fault.faultString) from None
    #
    if temporary:
      self.temporary[entry.uid] = entry.filename
      await self.store.add_temporary(entry.uid, entry.filename)
    #
    if front:
      self.queue.insert(0, entry)
    else:
      self.queue.append(entry)
    #
    self.log(entry.source + ' request: ' + entry.filename + (' by ' + entry.login if entry.login else ''))
    await self.changed()
  #

  async def remove(self, index):
    entry = self.queue.pop(index)
    await self.changed()
    return entry
  #

  async def clear(self):
    self.queue = []
    await self.changed()
  #

  def position_of(self, uid):
    return next((i for i, e in enumerate(self.queue) if e.uid == uid), None)
  #

  async def changed(self):
    await self.store.set_queue(self.queue)
    await self.apply_next()
    await self.controller.events.emit(events.PLAYLIST_CHANGED)
  #

  async def apply_next(self):
    # makes the first entry the server's next map; entries the server refuses are dropped
    while self.queue:
      entry = self.queue[0]
      try:
        await self.controller.server.choose_next_challenge(entry.filename)
        return
      except xmlrpc.client.Fault as fault:
        self.queue.pop(0)
        self.log('Dropped ' + entry.filename + ': ' + fault.faultString, log.LOG_WARNING)
        await self.controller.chat.announce('$fff' + strip_colors(entry.name) + '$z$s was dropped from the queue, '
          'the server can\'t play it.')
      #
    #
  #


  # ---- what the server does ----

  async def map_started(self, current):
    uid = current['UId']
    # the temporary map played before is done
    if self.playing_temporary is not None and self.playing_temporary != uid:
      await self.remove_temporary(self.playing_temporary)
    #
    self.playing_temporary = uid if uid in self.temporary else None
    if self.queue and self.queue[0].uid == uid:
      self.queue.pop(0)
    #
    await self.changed()
  #

  async def remove_temporary(self, uid):
    if uid not in self.temporary or self.position_of(uid) is not None:
      return # kept (/addthis) or requested again: it stays until it was played the last time
    #
    filename = self.temporary.pop(uid)
    await self.store.remove_temporary(uid)
    try:
      await self.controller.server.remove_challenge(filename)
    except xmlrpc.client.Fault as fault:
      self.log('Could not remove ' + filename + ': ' + fault.faultString, log.LOG_WARNING)
    #
  #

  async def list_changed(self, _):
    # maps were added or removed: requests for removed ones go, and the next index may have moved
    by_uid = self.controller.maps.by_uid
    gone = [uid for uid in self.temporary if uid not in by_uid]
    for uid in gone:
      del self.temporary[uid]
      await self.store.remove_temporary(uid)
    #
    if any(e.uid not in by_uid for e in self.queue):
      self.queue = [e for e in self.queue if e.uid in by_uid]
      await self.changed() # applies the next one
    else:
      await self.apply_next()
    #
  #

  async def replay(self, login='', nickname=''):
    # the current map once more, right after this one
    current = await self.controller.server.get_current_challenge_info()
    await self.request(Entry.from_map(current, login, nickname, source='Replay'), front=True)
  #


  # ---- commands ----

  async def coming(self):
    # [(name, why)] of the next maps: the requests, or the server's next map from its list
    if self.queue:
      return [(e.name, 'requested by ' + e.requested_by()) for e in self.queue]
    #
    m = await self.controller.server.get_next_challenge_info()
    return [(m['Name'], 'from the map list')]
  #

  async def cmd_nextmap(self, ctx):
    coming = await self.coming()
    if ctx.source == commands.GAME:
      rows = [('$ddd' + str(i + 1) + '.', '$fff' + strip_colors(name), '$ddd' + why) for i, (name, why) in enumerate(coming)]
      await self.next_window.open(ctx.login, 'Next maps', rows)
    else:
      name, why = coming[0]
      await ctx.reply('Next map: ' + strip_colors(name) + ' (' + why + ')')
    #
  #

  async def cmd_history(self, ctx):
    history = (await self.controller.maps.history(HISTORY + 1))[1:] # without the current map
    if not history:
      await ctx.reply('No maps were played yet.')
      return
    #
    if ctx.source == commands.GAME:
      rows = [('$ddd' + str(i + 1) + '.', '$fff' + strip_colors(name), '$ddd' + played_at[:16])
        for i, (uid, name, played_at) in enumerate(history)]
      await self.history_window.open(ctx.login, 'Played before', rows, hint='Times in UTC')
    else:
      await ctx.reply('\n'.join(str(i + 1) + '. ' + strip_colors(name) + ' (' + played_at[:16] + ')'
        for i, (uid, name, played_at) in enumerate(history[:10])))
    #
  #

  async def cmd_next(self, ctx):
    await self.controller.server.next_challenge() # first: the server may refuse (e.g. while the map changes)
    await self.controller.chat.announce(self.controller.admin.who(ctx) + ' skipped to the next map.')
  #

  async def cmd_restart(self, ctx):
    await self.controller.server.challenge_restart()
    await self.controller.chat.announce(self.controller.admin.who(ctx) + ' restarts the map.')
  #

  async def cmd_replay(self, ctx):
    try:
      await self.replay(ctx.login or '', ctx.display_name)
    except PlaylistError as exc:
      await ctx.reply(str(exc))
      return
    #
    await self.controller.chat.announce(self.controller.admin.who(ctx) + ' wants this map once more, it comes next.')
  #

  async def cmd_addthis(self, ctx):
    current = self.controller.maps.current
    if current is None or current['UId'] not in self.temporary:
      await ctx.reply('The current map is not a temporary map.')
      return
    #
    del self.temporary[current['UId']]
    self.playing_temporary = None
    await self.store.remove_temporary(current['UId'])
    if await self.controller.maps.save():
      await ctx.reply('$fff' + strip_colors(current['Name']) + '$z$s stays on the server (saved in the match settings).')
    else:
      await ctx.reply('$fff' + strip_colors(current['Name']) + '$z$s stays on the server until it restarts '
        '([maps] matchsettings is not set).')
    #
  #
#
