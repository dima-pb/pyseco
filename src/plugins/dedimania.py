import asyncio
import gzip
import re
import time
import urllib.request
import xmlrpc.client

from core import commands, events, log
from core.nations import nation
from core.text import strip_colors
from plugins.plugin import Plugin
from services.rankings import RankingWidget, RankingWindows, difference, ordinal, race_time


URL = 'http://dedimania.net:8002/Dedimania'
GAME = 'TMF'
STUNTS = 4
MIN_AUTHOR_TIME = 8000 # maps with a shorter author time have no Dedimania records
MIN_TIME = 6000 # shorter times are not sent
REFRESH = 240 # seconds between updates of the server's info
RETRY = 300 # seconds before trying again after Dedimania failed
LAN_LOGIN = re.compile(r'([/_]\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}[:_]\d+)$')
VERSION = '0.1'


class DedimaniaError(Exception):
  pass
#


class Client:
  # Dedimania's XML-RPC over HTTP. Every request is a system.multicall that starts with dedimania.Authenticate
  # and ends with dedimania.WarningsAndTTR (which reports the errors of the calls).

  def __init__(self, url, auth, timeout=20):
    self.url = url
    self.auth = auth
    self.timeout = timeout
  #

  async def call(self, method, *params):
    # one call; returns its result, raises DedimaniaError (Dedimania refused) or OSError (network)
    calls = [{'methodName': 'dedimania.Authenticate', 'params': [self.auth]},
      {'methodName': method, 'params': list(params)},
      {'methodName': 'dedimania.WarningsAndTTR', 'params': []}]
    body = xmlrpc.client.dumps((calls,), 'system.multicall', allow_none=True).encode('utf-8')
    data = await asyncio.to_thread(self.post, body)
    results = xmlrpc.client.loads(data)[0][0]
    if isinstance(results[0], dict) or not results[0][0]:
      raise DedimaniaError('authentication failed: ' + str(results[0]))
    #
    errors = [m['errors'] for m in results[2][0].get('methods', []) if m.get('errors')] if len(results) > 2 else []
    if isinstance(results[1], dict): # a fault
      raise DedimaniaError(results[1].get('faultString', str(results[1])))
    #
    if errors:
      raise DedimaniaError('; '.join(str(e) for e in errors))
    #
    return results[1][0]
  #

  def post(self, body):
    request = urllib.request.Request(self.url, gzip.compress(body), {'Content-Type': 'text/xml',
      'Content-Encoding': 'gzip', 'Accept-Encoding': 'gzip', 'User-Agent': 'pyseco/' + VERSION})
    with urllib.request.urlopen(request, timeout=self.timeout) as response:
      data = response.read()
      return gzip.decompress(data) if response.headers.get('Content-Encoding') == 'gzip' else data
    #
  #
#


class DediRecord:
  def __init__(self, login, nickname, time, checkpoints, new=False):
    self.login = login
    self.nickname = nickname
    self.time = time
    self.checkpoints = checkpoints
    self.new = new # driven on this server since the map started, sent to Dedimania at its end
    self.driven = 0 # when, for equal times
  #
#


class Dedimania(Plugin):
  # Dedimania, the world records of all servers (dedimania.net): the records of the map come when it starts,
  # new records are sent when it ends. A widget like the one of the local records shows them.
  # Dedimania is asked in the background, so a slow or unreachable Dedimania never holds up pyseco.
  #
  # Settings ([dedimania] in pyseco.toml):
  #   code = "..."     the server's Dedimania community code (or the server password); required
  #   login = "..."    the server login (default: the login the server runs with)
  #   nation = "GER"   the server's nation (3 letters)
  #   announce = 30    new records up to this rank are told to everybody, others only to the player
  #   top = 5          best records in the widget; below them the one to beat, the own and the last record
  #   send = true      false: only show the records, never send times (e.g. for a test server)
  # The widget is "dedimania", it can be moved with [widgets.dedimania].

  def __init__(self, controller):
    super().__init__(controller)
    settings = controller.settings('dedimania')
    self.code = str(settings.get('code', '')).strip()
    if not self.code:
      raise Exception('code (the Dedimania community code) must be set in the [dedimania] section of pyseco.toml')
    #
    self.login = str(settings.get('login', '')).strip()
    self.nation = str(settings.get('nation', 'OTH')).strip().upper()
    self.url = str(settings.get('url', URL))
    self.timeout = float(settings.get('timeout', 20)) # seconds to wait for Dedimania
    self.announce = int(settings.get('announce', 30))
    self.send_records = bool(settings.get('send', True))
    self.client = None
    self.queue = asyncio.Queue() # requests to Dedimania, sent in order by the worker
    self.worker_task = None
    self.ready = False # logged in to Dedimania
    self.failed_at = None # when Dedimania failed last
    self.last_update = time.monotonic()
    self.mode = None

    self.uid = None
    self.map = None
    self.valid = False # the map can have Dedimania records
    self.loaded = False # the records of the map are here
    self.records = [] # [DediRecord], best first
    self.max_rank = 30 # records the server may take
    self.player_ranks = {} # login -> how many records the player may take (more for Dedimania donors)
    self.banned = set()
    self.driven = 0

    # below the local records (with their default size)
    self.widget = RankingWidget(controller.ui, 'dedimania', 'Dedimania', 48, 3.7, int(settings.get('top', 5)),
      self.open_window)
    self.windows = RankingWindows(controller.ui)

    controller.events.register(events.MAP_STARTED, self.map_started)
    controller.events.register(events.MAP_ENDED, self.map_ended)
    controller.events.register(events.PLAYER_FINISHED, self.finished)
    controller.events.register(events.PLAYER_JOINED, self.player_joined)
    controller.events.register(events.PLAYER_LEFT, self.player_left)
    controller.events.register(events.SECOND_PASSED, self.second_passed)
    controller.commands.register('dedirecs', self.cmd_dedirecs, help='lists the Dedimania records of this map')
  #

  async def start(self):
    server = self.controller.server
    if not self.login:
      self.login = (await server.get_system_info())['ServerLogin']
    #
    self.client = Client(self.url, {'Game': GAME, 'Login': self.login, 'Password': self.code, 'Tool': 'pyseco',
      'Version': VERSION, 'Nation': self.nation, 'Packmask': await server.get_server_pack_mask(), 'PlayersGame': True},
      self.timeout)
    self.worker_task = asyncio.create_task(self.worker())
    self.send(self.connect)
    if self.controller.maps.current is not None:
      await self.map_started(self.controller.maps.current)
    #
  #

  async def stop(self):
    if self.worker_task is not None:
      self.worker_task.cancel()
    #
    await self.widget.hide()
  #

  def log(self, text, level=log.LOG_INFO):
    self.controller.logger.message('[dedimania] ' + text, level)
  #


  # ---- talking to Dedimania, in the background ----

  def send(self, request):
    # request: an async function without arguments, run by the worker
    self.queue.put_nowait(request)
  #

  async def worker(self):
    while True:
      request = await self.queue.get()
      if request != self.connect and not self.ready:
        continue # not logged in: dropped (records come again with the next map)
      #
      try:
        await request()
      except DedimaniaError as exc:
        if request == self.connect:
          self.log('Dedimania refused the login ' + self.login + ' (' + str(exc) + '), check login and code in '
            '[dedimania]; trying again in ' + str(RETRY // 60) + ' minutes', log.LOG_ERROR)
          self.failed_at = time.monotonic()
        else:
          self.log(request.__name__ + ': ' + str(exc), log.LOG_WARNING)
        #
      except (OSError, xmlrpc.client.Error, ValueError) as exc:
        self.log('Dedimania is not reachable (' + request.__name__ + ': ' + str(exc) + '), trying again in '
          + str(RETRY // 60) + ' minutes', log.LOG_WARNING)
        self.ready = False
        self.failed_at = time.monotonic()
      except Exception as exc:
        self.log(request.__name__ + ' failed: ' + repr(exc), log.LOG_ERROR)
      #
    #
  #

  async def connect(self):
    result = await self.client.call('dedimania.ValidateAccount')
    if not result.get('Status'):
      self.log('Dedimania refused the login ' + self.login + ', check login and code in [dedimania]', log.LOG_ERROR)
      self.failed_at = time.monotonic()
      return
    #
    self.ready = True
    self.failed_at = None
    self.log('Logged in to Dedimania as ' + self.login)
    for player in list(self.controller.players.online.values()):
      await self.arrive(player)
    #
    if self.uid is not None and not self.loaded:
      await self.load_records()
    #
  #

  async def second_passed(self, _):
    now = time.monotonic()
    if not self.ready:
      if self.failed_at is not None and now - self.failed_at > RETRY:
        self.failed_at = now
        self.send(self.connect)
      #
    elif now - self.last_update > REFRESH:
      self.last_update = now
      self.send(self.update_server)
    #
  #

  async def server_info(self):
    server = self.controller.server
    options = await server.get_server_options()
    online = list(self.controller.players.online.values())
    specs = sum(1 for p in online if p.is_spec)
    queue = self.controller.playlist.queue
    next_uid = queue[0].uid if queue else (await server.get_next_challenge_info())['UId']
    return {'SrvName': options['Name'], 'Comment': options['Comment'], 'Private': options['Password'] != '',
      'SrvIP': '', 'SrvPort': 0, 'XmlrpcPort': 0, 'NumPlayers': len(online) - specs,
      'MaxPlayers': options['CurrentMaxPlayers'], 'NumSpecs': specs, 'MaxSpecs': options['CurrentMaxSpectators'],
      'LadderMode': options['CurrentLadderMode'], 'NextFiveUID': next_uid}
  #

  async def player_info(self, login):
    # Dedimania's info about a player, None for LAN logins and players who left
    if LAN_LOGIN.search(login):
      return None
    #
    try:
      info = await self.controller.server.get_detailed_player_info(login)
    except xmlrpc.client.Fault:
      return None
    #
    path = info.get('Path', '').split('|')
    ladder = info.get('LadderStats', {})
    rankings = ladder.get('PlayerRankings') or [{}]
    return {'Login': login, 'Nation': nation(path[1] if len(path) > 1 else ''), 'TeamName': ladder.get('TeamName', ''),
      'TeamId': -1, 'IsSpec': info.get('IsSpectator', False), 'Ranking': rankings[0].get('Ranking', 0),
      'IsOff': info.get('IsInOfficialMode', False)}
  #

  async def players_info(self):
    infos = [await self.player_info(login) for login in list(self.controller.players.online)]
    return [info for info in infos if info is not None]
  #

  async def update_server(self):
    await self.client.call('dedimania.UpdateServerPlayers', GAME, self.mode or 1, await self.server_info(),
      await self.players_info())
  #

  async def arrive(self, player):
    info = await self.player_info(player.login)
    if info is None:
      return
    #
    result = await self.client.call('dedimania.PlayerArrive', GAME, player.login, player.nickname, info['Nation'],
      info['TeamName'], info['Ranking'], info['IsSpec'], info['IsOff'])
    self.player_ranks[player.login] = int(result.get('MaxRank', self.max_rank))
    if int(result.get('Status', 0)) % 2 == 1:
      self.banned.add(player.login)
      self.log(player.login + ' is banned on Dedimania, their finishes are not sent')
      await self.controller.chat.announce('$fff' + player.nickname + '$z$s is banned on Dedimania.')
    #
  #

  async def load_records(self):
    map, uid = self.map, self.uid
    result = await self.client.call('dedimania.CurrentChallenge', uid, map['Name'], map.get('Environnement', ''),
      map.get('Author', ''), GAME, self.mode, await self.server_info(), self.max_rank, await self.players_info())
    if uid != self.uid:
      return # the map changed meanwhile
    #
    self.max_rank = int(result.get('ServerMaxRecords', self.max_rank))
    self.records = [DediRecord(r['Login'], r['NickName'].replace('\n', ''), r['Best'], list(r.get('Checks', [])))
      for r in result.get('Records', [])]
    self.loaded = True
    self.log(str(len(self.records)) + ' records on ' + strip_colors(map['Name']))
    await self.show_all()
  #

  async def send_times(self):
    # the new records of the map that just ended
    map, records = self.ended_map, self.ended_records
    times = sorted((r for r in records if r.new and r.time >= MIN_TIME), key=lambda r: (r.time, r.driven))
    if not times:
      return
    #
    result = await self.client.call('dedimania.ChallengeRaceTimes', map['UId'], map['Name'],
      map.get('Environnement', ''), map.get('Author', ''), GAME, self.mode, len(times[0].checkpoints), self.max_rank,
      [{'Login': r.login, 'Best': r.time, 'Checks': ','.join(str(c) for c in r.checkpoints)} for r in times])
    self.log('Sent ' + str(len(times)) + ' new records of ' + strip_colors(map['Name']) + ', Dedimania has '
      + str(len(result.get('Records', []))))
  #


  # ---- what happens on the server ----

  async def map_started(self, map):
    self.map, self.uid = map, map['UId']
    self.records, self.loaded = [], False
    try:
      self.mode = await self.controller.server.get_game_mode()
    except xmlrpc.client.Fault:
      self.mode = 1
    #
    self.valid = self.mode != STUNTS and map.get('AuthorTime', MIN_AUTHOR_TIME) >= MIN_AUTHOR_TIME
    if not self.valid:
      self.log(strip_colors(map['Name']) + ' has no Dedimania records (stunts mode or author time below 8s)')
    #
    await self.show_all()
    if self.ready: # otherwise connect() loads them
      self.send(self.load_records)
    #
  #

  async def map_ended(self, map):
    if self.valid and self.loaded and map['UId'] == self.uid and self.send_records:
      self.ended_map, self.ended_records = self.map, list(self.records)
      self.send(self.send_times)
    #
  #

  async def player_joined(self, player):
    await self.show(player)
    if self.ready:
      async def player_arrive():
        await self.arrive(player)
      #
      self.send(player_arrive)
    #
  #

  async def player_left(self, player):
    self.banned.discard(player.login)
    if self.ready and not LAN_LOGIN.search(player.login):
      async def player_leave():
        await self.client.call('dedimania.PlayerLeave', GAME, player.login)
      #
      self.send(player_leave)
    #
  #

  async def finished(self, finish):
    login, time_ = finish.player.login, finish.time
    if not (self.valid and self.loaded) or finish.map['UId'] != self.uid or LAN_LOGIN.search(login):
      return
    #
    if login in self.banned:
      await self.controller.chat.tell(login, 'You are banned on Dedimania, your time is not sent.')
      return
    #
    if not finish.checkpoints or finish.checkpoints[-1] != time_:
      self.log(login + ': checkpoints do not match the finish (' + str(time_) + ', ' + str(finish.checkpoints)
        + '), ignored', log.LOG_WARNING)
      return
    #
    old_rank = next((i for i, r in enumerate(self.records) if r.login == login), None)
    old = self.records[old_rank] if old_rank is not None else None
    if old is not None and time_ >= old.time:
      return
    #
    rank = next((i for i, r in enumerate(self.records) if time_ < r.time and r is not old), len(self.records))
    if old is not None and old_rank < rank:
      rank -= 1 # the old record is removed above
    #
    if rank >= max(self.max_rank, self.player_ranks.get(login, 0)):
      return # not good enough for Dedimania
    #
    self.driven += 1
    record = DediRecord(login, finish.player.nickname, time_, list(finish.checkpoints), new=True)
    record.driven = self.driven
    if old is not None:
      self.records.remove(old)
    #
    self.records.insert(rank, record)
    gain = ' ($fff-' + difference(old.time - time_) + '$z$s)' if old is not None else ''
    text = '$fff' + finish.player.nickname + '$z$s ' + ('improved to' if old is not None else 'gained') + ' the $fff' \
      + ordinal(rank + 1) + '$z$s Dedimania record: $fff' + race_time(time_) + '$z$s' + gain
    if rank < self.announce:
      await self.controller.chat.announce(text)
    else:
      await self.controller.chat.tell(login, text)
    #
    self.log(login + ' ' + race_time(time_) + ': Dedimania rank ' + str(rank + 1))
    await self.show_all()
    await self.controller.events.emit(events.RECORD, events.NewRecord('dedimania', finish.player, time_, rank + 1,
      old.time if old else None, finish.map))
  #


  # ---- widget and windows ----

  async def show(self, player):
    if self.valid:
      await self.widget.show(player.login, player.nickname, self.records)
    else:
      await self.widget.hide(player.login)
    #
  #

  async def show_all(self):
    for player in list(self.controller.players.online.values()):
      await self.show(player)
    #
  #

  async def open_window(self, login):
    own = next((r for r in self.records if r.login == login), None)
    name = strip_colors(self.map['Name']) if self.map else ''
    await self.windows.open(login, 'Dedimania Records on ' + name, self.records, own, dates=False)
  #

  async def cmd_dedirecs(self, ctx):
    if ctx.source == commands.GAME:
      await self.open_window(ctx.login)
    elif not self.records:
      await ctx.reply('No Dedimania records on this map' + ('' if self.loaded else ' (not loaded)') + '.')
    else:
      await ctx.reply('\n'.join(str(i + 1) + '. ' + race_time(r.time) + ' ' + strip_colors(r.nickname)
        for i, r in enumerate(self.records[:10])))
    #
  #
#
