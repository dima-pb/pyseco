import json
import xmlrpc.client

import accounts
import commands
import log
from plugins.plugin import Plugin
import utilities


# Echo protocol with the XAseco side (xaseco addon plugin.rasp_jukebox.php, which stands in for RASP's jukebox):
# The server swaps the Echo parameters: Echo(a, b) arrives as callback (b, a), and XAseco only passes a on.
# So every message is sent as Echo('<channel>|<json>', '<channel>').
TO_XASECO = 'pyseco'
FROM_XASECO = 'pyseco-shim'

LIST_PAGE = 8

class Entry:
  # one map in the jukebox; source: Jukebox, Replay, TMX, Admin, ...

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
    return Entry(m['UId'], m['FileName'], m['Name'], m.get('Environment', ''), login, nickname, source)
  #

  def for_xaseco(self, temporary):
    # the fields of an entry in RASP's $jukebox, as XAseco plugins (Records-Eyepiece) expect them
    return {'uid': self.uid, 'FileName': self.filename, 'Name': self.name, 'Env': self.environment,
      'Login': self.login, 'Nick': self.nickname, 'source': self.source, 'tmx': temporary}
  #
#


class Jukebox(Plugin):
  # Players wish maps to be played next. The jukebox owns "which map comes next": it sets the server's
  # next map right away whenever the first entry changes, so skips and votes work too.
  # Temporary maps (from TMX) are removed from the server after they were played, unless kept with /addthis.
  #
  # Settings ([jukebox] in pyseco.toml):
  #   recent = 10       players can't jukebox one of the last <recent> maps (operators and above can)
  #   per_player = 1    entries per player at a time (operators and above: no limit)

  def __init__(self, controller):
    super().__init__(controller)
    settings = controller.settings('jukebox')
    self.recent = int(settings.get('recent', 10))
    self.per_player = int(settings.get('per_player', 1))
    self.store = None # storage.interfaces.JukeboxStore
    self.queue = [] # [Entry], stored as QueuedMap (same fields)
    self.temporary = {} # uid -> filename of maps to remove after they were played
    self.playing_temporary = None # uid of the temporary map being played

    controller.register_event('MapStarted', self.map_started)
    controller.register_event('TrackMania.ChallengeListModified', self.list_modified)
    controller.register_event('TrackMania.Echo', self.echo)

    register = controller.commands.register
    register('list', self.cmd_list, help='lists the maps on the server', usage='[page | search text]')
    register('jukebox', self.cmd_jukebox, help='wishes the map with this number (see /list) to be played next',
      usage='[<number> | list | drop | drop <position> | clear]', aliases=('jb',))
    register('nextmap', self.cmd_nextmap, help='shows the next map')
    register('history', self.cmd_history, help='shows the recently played maps')
    register('addthis', self.cmd_addthis, role=accounts.ADMIN, help='keeps the current temporary (TMX) map on the server')
  #

  async def start(self):
    self.store = self.controller.storage.jukebox
    self.queue = [Entry(q.uid, q.filename, q.name, q.environment, q.login, q.nickname, q.source)
      for q in await self.store.queue()]
    self.temporary = await self.store.temporary_maps()
    current = self.controller.maps.current
    if current is not None and current['UId'] in self.temporary:
      self.playing_temporary = current['UId']
    #
    await self.apply_next()
    await self.publish()
  #

  def log(self, text, level=log.LOG_INFO):
    self.controller.logger.message('[jukebox] ' + text, level)
  #

  async def announce(self, text):
    await self.controller.chat_send_server_message('$fb0»$z$s ' + text)
  #


  # ---- queue ----

  async def add(self, entry, role, reply, front=False, temporary=False):
    # checks the rules, then queues the map; reply(text) tells the requester why not
    if any(e.uid == entry.uid for e in self.queue):
      await reply('This map is already in the jukebox.')
      return False
    #
    if role < accounts.OPERATOR:
      if entry.login and sum(1 for e in self.queue if e.login == entry.login) >= self.per_player:
        await reply('You already have a map in the jukebox (/jukebox drop removes it).')
        return False
      #
      # the current map counts as played (a replay goes through the vote)
      if entry.uid in [uid for uid, _, _ in await self.controller.maps.history(self.recent + 1)]:
        await reply('This map was played recently, choose another one.')
        return False
      #
    #
    if entry.uid not in self.controller.maps.by_uid:
      # a new file (TMX): the server has to take it into its list first
      try:
        await self.controller.call('AddChallenge', entry.filename)
      except xmlrpc.client.Fault as fault:
        await reply('The server did not accept the map: ' + fault.faultString)
        return False
      #
      await self.controller.maps.refresh()
    #
    try:
      await self.controller.call('CheckChallengeForCurrentServerParams', entry.filename)
    except xmlrpc.client.Fault as fault:
      await reply('The map does not fit the server settings: ' + fault.faultString)
      return False
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
    await self.changed()
    who = utilities.strip_colors(entry.nickname) if entry.nickname else entry.source
    await self.announce('$fff' + utilities.strip_colors(entry.name) + '$z$s was added to the jukebox by $fff' + who + '$z$s.')
    return True
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

  async def changed(self):
    await self.store.set_queue(self.queue)
    await self.apply_next()
    await self.publish()
  #

  async def apply_next(self):
    # makes the first entry the server's next map; entries the server refuses are dropped
    while self.queue:
      entry = self.queue[0]
      try:
        await self.controller.call('ChooseNextChallenge', entry.filename)
        return
      except xmlrpc.client.Fault as fault:
        self.queue.pop(0)
        self.log('Dropped ' + entry.filename + ' from the jukebox: ' + fault.faultString, log.LOG_WARNING)
        await self.announce('$fff' + utilities.strip_colors(entry.name) + '$z$s was dropped from the jukebox, '
          'the server can\'t play it.')
      #
    #
  #

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
    if uid not in self.temporary or any(e.uid == uid for e in self.queue):
      return # kept (/addthis) or wished again: it stays until it was played the last time
    #
    filename = self.temporary.pop(uid)
    await self.store.remove_temporary(uid)
    try:
      await self.controller.call('RemoveChallenge', filename)
    except xmlrpc.client.Fault as fault:
      self.log('Could not remove ' + filename + ': ' + fault.faultString, log.LOG_WARNING)
    #
  #

  async def list_modified(self, params):
    if params[2]: # maps were added or removed, the next index may have moved
      await self.apply_next()
    #
  #


  # ---- XAseco side ----

  async def publish(self):
    # sends queue and history to the XAseco side, which mirrors them for Records-Eyepiece
    history = list(reversed(await self.controller.maps.recent_uids(20)))
    state = {'queue': [e.for_xaseco(e.uid in self.temporary) for e in self.queue], 'history': history}
    try:
      await self.controller.call('Echo', TO_XASECO + '|' + json.dumps(state), TO_XASECO)
    except xmlrpc.client.Fault as fault:
      self.log('Could not publish the jukebox: ' + fault.faultString, log.LOG_WARNING)
    #
  #

  async def echo(self, params):
    if len(params) != 2 or not params[1].startswith(FROM_XASECO + '|'):
      return
    #
    request = json.loads(params[1][len(FROM_XASECO) + 1:])
    action = request.get('action')
    login = request.get('login') or ''
    # XAseco checked its own admin rights already
    role = max(await self.controller.accounts.role(login or None), accounts.ADMIN if request.get('admin') else accounts.PLAYER)
    reply = (lambda text: self.controller.chat_to(login, text)) if login else self.no_reply
    if action == 'hello':
      await self.publish()
    elif action == 'add':
      m = self.controller.maps.by_uid.get(request['uid'])
      entry = Entry.from_map(m, login, request.get('nickname', ''), request.get('source', 'Jukebox')) if m else \
        Entry(request['uid'], request['filename'], request.get('name', ''), request.get('env', ''), login,
          request.get('nickname', ''), request.get('source', 'Jukebox'))
      if not await self.add(entry, role, reply, front=request.get('source', '').endswith('Replay'),
          temporary=bool(request.get('tmx'))):
        await self.publish() # undo what the XAseco side assumed
      #
    elif action == 'drop':
      index = next((i for i, e in enumerate(self.queue) if e.uid == request.get('uid')), None)
      if index is not None and (role >= accounts.OPERATOR or self.queue[index].login == login):
        await self.remove(index)
      else:
        await self.publish()
      #
    elif action == 'clear' and role >= accounts.ADMIN:
      await self.clear()
    else:
      await self.publish()
    #
  #

  async def no_reply(self, text):
    pass
  #


  # ---- commands ----

  def map_line(self, index, m):
    return str(index + 1) + '. $fff' + utilities.strip_colors(m['Name']) + '$z$s by ' + (m.get('Author') or '?')
  #

  async def cmd_list(self, ctx):
    maps = list(enumerate(self.controller.maps.list))
    page = 1
    if len(ctx.args) == 1 and ctx.args[0].isdigit():
      page = int(ctx.args[0])
    elif ctx.args:
      words = [w.lower() for w in ctx.args]
      maps = [(i, m) for i, m in maps if all(w in (utilities.strip_colors(m['Name']) + ' ' + m.get('Author', '')).lower()
        for w in words)]
      if not maps:
        await ctx.reply('No map matches "' + ' '.join(ctx.args) + '".')
        return
      #
    #
    pages = max(1, (len(maps) + LIST_PAGE - 1) // LIST_PAGE)
    page = min(max(page, 1), pages)
    shown = maps[(page - 1) * LIST_PAGE:page * LIST_PAGE]
    prefix = '/' if ctx.source == commands.GAME else '!'
    await ctx.reply('Maps ' + str(page) + '/' + str(pages) + ' (' + prefix + 'jukebox <number> to wish one, '
      + prefix + 'list <page> for more):')
    for i, m in shown:
      await ctx.reply(self.map_line(i, m))
    #
  #

  async def cmd_jukebox(self, ctx):
    args = [a.lower() for a in ctx.args]
    if not args or args == ['list']:
      if not self.queue:
        await ctx.reply('The jukebox is empty.')
      #
      for i, e in enumerate(self.queue):
        await ctx.reply(str(i + 1) + '. $fff' + utilities.strip_colors(e.name) + '$z$s ('
          + (utilities.strip_colors(e.nickname) or e.source) + ')')
      #
    elif args[0].isdigit() and len(args) == 1:
      if ctx.login is None:
        await ctx.reply('Link your discord account first (/link in game).')
        return
      #
      number = int(args[0])
      if not 1 <= number <= len(self.controller.maps.list):
        await ctx.reply('There is no map ' + args[0] + ', see /list.')
        return
      #
      player = self.controller.players.get(ctx.login)
      nickname = player.nickname if player else ctx.display_name
      entry = Entry.from_map(self.controller.maps.list[number - 1], ctx.login, nickname)
      await self.add(entry, ctx.role, ctx.reply)
    elif args == ['drop']:
      index = next((i for i, e in enumerate(self.queue) if ctx.login and e.login == ctx.login), None)
      if index is None:
        await ctx.reply('You have no map in the jukebox.')
      else:
        entry = await self.remove(index)
        await ctx.reply('Removed ' + utilities.strip_colors(entry.name) + ' from the jukebox.')
      #
    elif args[0] == 'drop' and len(args) == 2 and args[1].isdigit() and ctx.role >= accounts.OPERATOR:
      position = int(args[1])
      if not 1 <= position <= len(self.queue):
        await ctx.reply('The jukebox has no position ' + args[1] + '.')
        return
      #
      entry = await self.remove(position - 1)
      await self.announce('$fff' + utilities.strip_colors(entry.name) + '$z$s was removed from the jukebox.')
    elif args == ['clear'] and ctx.role >= accounts.ADMIN:
      await self.clear()
      await self.announce('The jukebox was cleared.')
    else:
      raise commands.UsageError()
    #
  #

  async def cmd_nextmap(self, ctx):
    if self.queue:
      e = self.queue[0]
      await ctx.reply('Next map: $fff' + utilities.strip_colors(e.name) + '$z$s (jukebox: '
        + (utilities.strip_colors(e.nickname) or e.source) + ')')
      return
    #
    m = await self.controller.call('GetNextChallengeInfo')
    await ctx.reply('Next map: $fff' + utilities.strip_colors(m['Name']) + '$z$s')
  #

  async def cmd_history(self, ctx):
    history = await self.controller.maps.history(11)
    if len(history) < 2:
      await ctx.reply('No maps were played yet.')
      return
    #
    for i, (uid, name, played_at) in enumerate(history[1:]):
      await ctx.reply(str(i + 1) + '. $fff' + utilities.strip_colors(name) + '$z$s (' + played_at + ')')
    #
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
    await self.publish()
    await ctx.reply('$fff' + utilities.strip_colors(current['Name']) + '$z$s stays on the server. '
      'To keep it after a server restart, save the map list (/admin writetracklist).')
  #
#
