import asyncio
import http.client
import json
import urllib.parse
import xmlrpc.client

from core import commands, events, log, roles
from core.text import strip_colors
from plugins.plugin import Plugin
from services.playlist import Entry, PlaylistError
from services.rankings import RankingWidget, RankingWindows, race_time
from services.ui import link
from services.windows import ListWindow


URL = 'https://tmnf.exchange'
TRACK_FIELDS = ('TrackId,TrackName,UId,Authors,UnlimiterVersion,Environment,Car,PrimaryType,AuthorTime,Awards,Tags,'
  'Difficulty,UploadedAt,WRReplay.ReplayTime,WRReplay.User.Name')
RANDOM = 'primarytype=0' # default filter for random maps: race maps
SAFE = {'inunlimiter': '0', 'inenvmix': '0'} # always part of the random filter
DIFFICULTIES = {0: 'Beginner', 1: 'Intermediate', 2: 'Expert', 3: 'Lunatic'}
VERSION = '0.1'


class TmxError(Exception):
  pass
#


class Client:
  # TMNF-X (tmnf.exchange): track infos, replays, random tracks and downloads, over HTTP(S) in a thread

  def __init__(self, url, timeout=15):
    self.url = urllib.parse.urlsplit(url)
    self.timeout = timeout
  #

  def request(self, path):
    # -> (status, headers, body); redirects are not followed
    cls = http.client.HTTPSConnection if self.url.scheme == 'https' else http.client.HTTPConnection
    connection = cls(self.url.netloc, timeout=self.timeout)
    try:
      connection.request('GET', path, headers={'User-Agent': 'pyseco/' + VERSION})
      response = connection.getresponse()
      return response.status, response, response.read()
    finally:
      connection.close()
    #
  #

  async def get(self, path):
    status, response, body = await asyncio.to_thread(self.request, path)
    if status != 200:
      raise TmxError('TMX answered ' + str(status) + ' for ' + path.split('?')[0])
    #
    return body
  #

  async def tracks(self, **query):
    body = await self.get('/api/tracks?' + urllib.parse.urlencode(dict(query, fields=TRACK_FIELDS)))
    return json.loads(body)['Results']
  #

  async def track(self, track_id):
    # the track's infos (TRACK_FIELDS) or None
    results = await self.tracks(id=track_id)
    return results[0] if results else None
  #

  async def track_by_uid(self, uid):
    results = await self.tracks(uid=uid)
    return results[0] if results else None
  #

  async def random_id(self, query):
    # TMX answers /trackrandom with a redirect to /trackshow/<id>
    status, response, body = await asyncio.to_thread(self.request, '/trackrandom?' + query)
    location = response.getheader('Location') or ''
    if status not in (301, 302) or '/trackshow/' not in location:
      raise TmxError('no random track found (TMX answered ' + str(status) + ')')
    #
    return int(location.rsplit('/', 1)[1])
  #

  async def download(self, track_id):
    return await self.get('/trackgbx/' + str(track_id))
  #

  async def replays(self, track_id, count):
    body = await self.get('/api/replays?' + urllib.parse.urlencode({'trackId': track_id, 'count': count,
      'fields': 'ReplayId,ReplayTime,User.Name,ReplayAt'}))
    return json.loads(body)['Results']
  #

  async def tag_names(self):
    return {t['Id']: t['Name'] for t in json.loads(await self.get('/api/meta/tags'))}
  #
#


def unsafe(track):
  # why the track can't run on a normal server, or None
  if track.get('UnlimiterVersion') is not None:
    return 'it needs TMUnlimiter'
  #
  if track.get('Environment') != track.get('Car'):
    return 'it is an environment mix'
  #
  return None
#


class Replay:
  # a TMX replay in a ranking; a click on it downloads it
  def __init__(self, replay):
    self.login = ''
    self.nickname = replay['User']['Name']
    self.time = replay['ReplayTime']
    self.date = replay.get('ReplayAt', '')
    self.checkpoints = []
    self.url = URL + '/recordgbx/' + str(replay['ReplayId']) if replay.get('ReplayId') else None
  #
#


class Tmx(Plugin):
  # TMNF-X: admins add maps by their TMX id (/add) or at random (/rtmx), /tmxinfo shows what TMX knows about the
  # current map, a widget its best TMX times (a click on one downloads the replay). Maps from TMX are temporary: the playlist removes them after
  # they were played, unless an admin keeps them with /addthis.
  # Maps that need TMUnlimiter or mix environments never get on the server.
  #
  # Settings ([tmx] in pyseco.toml):
  #   random = "primarytype=0"   TMX search filter for /rtmx (see tmnf.exchange's track search); no unlimiter
  #                              and no environment mix are always added
  #   top = 5                    TMX times in the widget (0: no widget)
  # The widget is "tmx", it can be moved with [widgets.tmx].

  def __init__(self, controller):
    super().__init__(controller)
    settings = controller.settings('tmx')
    self.client = Client(str(settings.get('url', URL)), float(settings.get('timeout', 15)))
    query = dict(urllib.parse.parse_qsl(str(settings.get('random', RANDOM))))
    self.random_query = urllib.parse.urlencode(dict(query, **SAFE))
    self.top = int(settings.get('top', 5))
    self.track = None # TMX infos of the current map, None if it is not on TMX
    self.replays = []
    self.uid = None
    self.tags = None # TMX tag id -> name, loaded once
    self.busy = asyncio.Lock() # one download at a time
    self.tasks = set()

    ui = controller.ui
    self.info_window = ListWindow(ui, width=80, columns=[16, 60])
    self.windows = RankingWindows(ui)
    # below the Dedimania records (with their default size)
    self.widget = RankingWidget(ui, 'tmx', 'TMX', 48, -18.7, self.top, self.open_replays, personal=False) \
      if self.top > 0 else None

    controller.events.register(events.MAP_STARTED, self.map_started)
    controller.events.register(events.PLAYER_JOINED, self.player_joined)
    register = controller.commands.register
    register('add', self.cmd_add, role=roles.ADMIN, help='adds maps from TMX for one play (keep them with /addthis)',
      usage='<TMX id> [<TMX id> ...]')
    register('rtmx', self.cmd_rtmx, role=roles.ADMIN, help='adds random maps from TMX for one play', usage='[1-10]')
    register('tmxinfo', self.cmd_tmxinfo, help='shows what TMX knows about this map')
  #

  async def start(self):
    if self.controller.maps.current is not None:
      await self.map_started(self.controller.maps.current)
    #
  #

  async def stop(self):
    for task in self.tasks:
      task.cancel()
    #
    if self.widget is not None:
      await self.widget.hide()
    #
  #

  def log(self, text, level=log.LOG_INFO):
    self.controller.logger.message('[tmx] ' + text, level)
  #

  def background(self, coroutine):
    # TMX can be slow: requests run beside pyseco, never in an event handler
    task = asyncio.create_task(coroutine)
    self.tasks.add(task)
    task.add_done_callback(self.tasks.discard)
  #


  # ---- the current map ----

  async def map_started(self, map):
    self.uid, self.track, self.replays = map['UId'], None, []
    await self.show_all()
    self.background(self.load(map['UId']))
  #

  async def load(self, uid):
    try:
      track = await self.client.track_by_uid(uid)
      replays = await self.client.replays(track['TrackId'], max(self.top, 25)) if track else []
    except (OSError, TmxError, ValueError, KeyError) as exc:
      self.log('No TMX infos for ' + uid + ': ' + str(exc), log.LOG_WARNING)
      return
    #
    if uid != self.uid:
      return # the map changed meanwhile
    #
    # TMX lists several replays of a player, the ranking keeps the best one (they come best first)
    seen = set()
    self.track, self.replays = track, []
    for replay in replays:
      if replay['User']['Name'] not in seen:
        seen.add(replay['User']['Name'])
        self.replays.append(Replay(replay))
      #
    #
    await self.show_all()
  #

  async def show(self, player):
    if self.widget is None:
      return
    #
    if self.track is None:
      await self.widget.hide(player.login)
    else:
      await self.widget.show(player.login, player.nickname, self.replays)
    #
  #

  async def show_all(self):
    for player in list(self.controller.players.online.values()):
      await self.show(player)
    #
  #

  async def player_joined(self, player):
    await self.show(player)
  #

  async def open_replays(self, login):
    if self.track is not None:
      await self.windows.open(login, 'TMX times on ' + self.track['TrackName'], self.replays, None, checkpoints=False,
        hint='Click a name to download the replay')
    #
  #


  # ---- adding maps ----

  async def add(self, track_id, ctx, check_type=False):
    # loads the map from TMX onto the server and asks the playlist for it; returns the track or None (ctx told why)
    track = await self.client.track(track_id)
    if track is None:
      await ctx.reply('There is no map ' + str(track_id) + ' on TMX.')
      return None
    #
    reason = unsafe(track) or ('it is no race map' if check_type and track.get('PrimaryType') != 0 else None)
    if reason:
      await ctx.reply(track['TrackName'] + ' (' + str(track_id) + ') can\'t be added: ' + reason + '.')
      return None
    #
    maps = self.controller.maps
    temporary = track['UId'] not in maps.by_uid
    if temporary:
      filename = 'Challenges\\TMX\\' + str(track_id) + '.Challenge.Gbx'
      data = await self.client.download(track_id)
      try:
        await self.controller.server.write_file(filename, xmlrpc.client.Binary(data))
      except xmlrpc.client.Fault as fault:
        await ctx.reply('The server did not take the file: ' + fault.faultString)
        return None
      #
    else:
      filename = maps.by_uid[track['UId']]['FileName']
    #
    nickname = ctx.display_name
    player = self.controller.players.online.get(ctx.login or '')
    if player is not None:
      nickname = player.nickname
    #
    entry = Entry(track['UId'], filename, track['TrackName'], 'Stadium', ctx.login or '', nickname, source='TMX')
    try:
      await self.controller.playlist.request(entry, temporary=temporary)
    except PlaylistError as exc:
      await ctx.reply(track['TrackName'] + ': ' + str(exc))
      return None
    #
    self.log((ctx.login or ctx.display_name) + ' added TMX ' + str(track_id) + ' ' + track['TrackName'])
    await self.controller.chat.announce('$fff' + nickname + '$z$s added $fff' + track['TrackName'] + '$z$s from TMX ('
      + str(track_id) + ').')
    return track
  #

  async def cmd_add(self, ctx):
    if not ctx.args or not all(a.isdigit() for a in ctx.args):
      raise commands.UsageError()
    #
    async def run():
      async with self.busy:
        for arg in ctx.args:
          try:
            await self.add(int(arg), ctx)
          except (OSError, TmxError, ValueError) as exc:
            await ctx.reply('TMX is not reachable: ' + str(exc))
            return
          #
        #
      #
    #
    self.background(run())
  #

  async def cmd_rtmx(self, ctx):
    if len(ctx.args) > 1 or (ctx.args and not ctx.args[0].isdigit()):
      raise commands.UsageError()
    #
    count = int(ctx.args[0]) if ctx.args else 1
    if not 1 <= count <= 10:
      raise commands.UsageError('1 to 10 maps.')
    #
    async def run():
      async with self.busy:
        added, tries = 0, 0
        while added < count and tries < count * 3:
          tries += 1
          try:
            if await self.add(await self.client.random_id(self.random_query), ctx, check_type=True) is not None:
              added += 1
            #
          except (OSError, TmxError, ValueError) as exc:
            await ctx.reply('TMX is not reachable: ' + str(exc))
            return
          #
        #
        if added < count:
          await ctx.reply('Only ' + str(added) + ' of ' + str(count) + ' random maps could be added.')
        #
      #
    #
    self.background(run())
  #


  # ---- infos ----

  async def info_rows(self):
    track = self.track
    if self.tags is None:
      try:
        self.tags = await self.client.tag_names()
      except (OSError, TmxError, ValueError):
        self.tags = {}
      #
    #
    wr = track.get('WRReplay') or {}
    page = URL + '/trackshow/' + str(track['TrackId'])
    rows = [
      ('Name', '$fff' + track['TrackName']),
      ('Author', ', '.join(a['User']['Name'] for a in track.get('Authors', []))),
      ('TMX id', str(track['TrackId'])),
      ('Uploaded', (track.get('UploadedAt') or '')[:10]),
      ('Author time', race_time(track.get('AuthorTime', 0))),
      ('Difficulty', DIFFICULTIES.get(track.get('Difficulty'), '?')),
      ('Tags', ', '.join(self.tags.get(t, str(t)) for t in track.get('Tags', []))),
      ('Awards', str(track.get('Awards', 0))),
      ('World record', race_time(wr['ReplayTime']) + ' by ' + wr['User']['Name'] if wr.get('ReplayTime') else '-'),
      ('Page', link(page, page[len('https://'):])),
    ]
    return [('$ddd' + key, value) for key, value in rows]
  #

  async def cmd_tmxinfo(self, ctx):
    if self.track is None:
      await ctx.reply('This map is not on TMX' + ('' if self.uid else ' (no map yet)') + '.')
      return
    #
    rows = await self.info_rows()
    if ctx.source == commands.GAME:
      await self.info_window.open(ctx.login, 'TMX: ' + self.track['TrackName'], rows)
    else:
      rows[-1] = (rows[-1][0], URL + '/trackshow/' + str(self.track['TrackId'])) # no TM link on discord
      await ctx.reply('\n'.join(strip_colors(key) + ': ' + strip_colors(value) for key, value in rows))
    #
  #
#
