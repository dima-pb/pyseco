from core import commands, events, log
from core.text import strip_colors
from plugins.plugin import Plugin
from services.rankings import RankingWidget, RankingWindows, difference, ordinal, race_time


class LocalRecords(Plugin):
  # The best time of every player on every map, with the checkpoints of the run (to spot cheats and shortcuts).
  # The best <max> of a map are its local records. Equal times: who drove it first is first.
  #
  # A widget shows the top 3, the records around the player's own and the player's own line; a click on it
  # (or /records) opens all records, a click on a record there compares its checkpoints with the player's own.
  #
  # Settings ([local_records] in pyseco.toml):
  #   max = 50            records per map
  #   announce = 30       new records up to this rank are told to everybody (0: never)
  #   tell_player = true  a player who improves without being announced is told privately
  #   top = 5             best records in the widget; below them the one to beat, the own and the last record
  # The widget is "local_records", it can be moved with [widgets.local_records].

  def __init__(self, controller):
    super().__init__(controller)
    settings = controller.settings('local_records')
    self.max = int(settings.get('max', 50))
    self.announce = int(settings.get('announce', 30))
    self.tell_player = bool(settings.get('tell_player', True))
    self.store = controller.storage.records
    self.ranking = [] # [Record] of the current map
    self.uid = None

    self.widget = RankingWidget(controller.ui, 'local_records', 'Local Records', 48, 26.5,
      int(settings.get('top', 5)), self.open_window)
    self.windows = RankingWindows(controller.ui)

    controller.events.register(events.MAP_STARTED, self.map_started)
    controller.events.register(events.PLAYER_FINISHED, self.finished)
    controller.events.register(events.PLAYER_JOINED, self.player_joined)
    controller.commands.register('records', self.cmd_records, help='lists the local records of this map')
  #

  async def start(self):
    if self.controller.maps.current is not None:
      await self.map_started(self.controller.maps.current)
    #
  #

  async def stop(self):
    await self.widget.hide()
  #

  def log(self, text):
    self.controller.logger.message('[local_records] ' + text, log.LOG_INFO)
  #

  def rank_of(self, login):
    # 0-based position in the ranking or None
    return next((i for i, r in enumerate(self.ranking) if r.login == login), None)
  #


  # ---- records ----

  async def map_started(self, map):
    self.uid = map['UId']
    self.ranking = await self.store.ranking(self.uid, self.max)
    await self.show_all()
  #

  async def finished(self, finish):
    uid, login = finish.map['UId'], finish.player.login
    if uid != self.uid:
      return
    #
    old = await self.store.best(uid, login)
    if old is not None and finish.time >= old.time:
      return
    #
    old_rank = self.rank_of(login)
    await self.store.save(uid, login, finish.time, finish.checkpoints)
    self.ranking = await self.store.ranking(uid, self.max)
    rank = self.rank_of(login)
    self.log(login + ' ' + race_time(finish.time) + ' on ' + uid + (' rank ' + str(rank + 1) if rank is not None else ''))
    await self.tell(finish.player, finish.time, old, old_rank, rank)
    if rank is not None:
      await self.show_all()
    #
  #

  async def tell(self, player, time, old, old_rank, rank):
    gain = ' ($fff-' + difference(old.time - time) + '$z$s)' if old is not None else ''
    if rank is not None and rank < self.announce:
      what = 'improved to' if old_rank is not None else 'drove'
      await self.controller.chat.announce('$fff' + player.nickname + '$z$s ' + what + ' the $fff' + ordinal(rank + 1)
        + '$z$s local record: $fff' + race_time(time) + '$z$s' + gain)
    elif self.tell_player:
      place = 'the ' + ordinal(rank + 1) + ' local record' if rank is not None else 'not in the top ' + str(self.max)
      await self.controller.chat.tell(player.login, 'Your best time: $fff' + race_time(time) + '$z$s' + gain + ', '
        + place + '.')
    #
  #


  # ---- widget and windows ----

  async def show(self, player):
    await self.widget.show(player.login, player.nickname, self.ranking)
  #

  async def show_all(self):
    for player in list(self.controller.players.online.values()):
      await self.show(player)
    #
  #

  async def player_joined(self, player):
    await self.show(player)
  #

  async def open_window(self, login):
    name = strip_colors(self.controller.maps.current['Name']) if self.controller.maps.current else ''
    own = await self.store.best(self.uid, login) if self.uid else None
    await self.windows.open(login, 'Local Records on ' + name, self.ranking, own)
  #

  async def cmd_records(self, ctx):
    if ctx.source == commands.GAME:
      await self.open_window(ctx.login)
    elif not self.ranking:
      await ctx.reply('No local records on this map yet.')
    else:
      await ctx.reply('\n'.join(str(i + 1) + '. ' + race_time(r.time) + ' ' + strip_colors(r.nickname)
        for i, r in enumerate(self.ranking[:10])))
    #
  #
#
