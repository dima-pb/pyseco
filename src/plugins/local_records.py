from core import commands, events, log
from core.text import strip_colors
from plugins.plugin import Plugin
from services.ui import frame, label, quad
from services.windows import ROW_STYLE, TITLE_STYLE, WINDOW_STYLE, ListWindow


def race_time(ms):
  # 9080 -> '0:09.08'
  minutes, rest = divmod(max(ms, 0), 60000)
  return str(minutes) + ':' + str(rest // 1000).zfill(2) + '.' + str(rest % 1000 // 10).zfill(2)
#


def difference(ms):
  # 40 -> '0.04', 61230 -> '61.23'
  return str(ms // 1000) + '.' + str(ms % 1000 // 10).zfill(2)
#


def ordinal(n):
  return str(n) + ('th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th'))
#


LINE = 2.2


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
  #   lines = 5           records in the widget (the top 3 and the ones around the player's own)
  # The widget is "local_records", it can be moved with [widgets.local_records].

  def __init__(self, controller):
    super().__init__(controller)
    settings = controller.settings('local_records')
    self.max = int(settings.get('max', 50))
    self.announce = int(settings.get('announce', 30))
    self.tell_player = bool(settings.get('tell_player', True))
    self.lines = max(int(settings.get('lines', 5)), 1)
    self.top = min(3, self.lines)
    self.store = controller.storage.records
    self.ranking = [] # [Record] of the current map
    self.uid = None

    ui = controller.ui
    self.widget_id = ui.manialink_id()
    self.widget_x, self.widget_y = ui.position('local_records', 48, 26.5)
    self.open_action = ui.actions(1, self.title_clicked)
    self.window = ListWindow(ui, width=90, columns=[7, 14, 46, 19])
    self.checkpoints_window = ListWindow(ui, width=70, page_size=20, columns=[12, 18, 18, 18])

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
    await self.controller.ui.hide(self.widget_id)
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


  # ---- widget ----

  def shown_ranks(self, own):
    # positions in the ranking the widget shows: the top, then the ones around the player's own record
    count = len(self.ranking)
    if count <= self.lines:
      return list(range(count))
    #
    rest = self.lines - self.top
    if own is None or own < self.lines or rest == 0:
      return list(range(self.lines))
    #
    start = min(max(own - rest // 2, self.top), count - rest)
    return list(range(self.top)) + list(range(start, start + rest))
  #

  def render(self, login):
    own = self.rank_of(login)
    width, height = 16, 3.6 + (self.lines + 1) * LINE + 0.8
    # everything is clickable, it opens all records
    parts = [quad(0, 0, 0, width, height, *WINDOW_STYLE, action=self.open_action),
      quad(0.4, -0.4, 1, width - 0.8, 2.8, *TITLE_STYLE, action=self.open_action),
      label(1, -1.8, 2, '$fffLocal Records', width - 2, 2, size=1, valign='center')]
    lines = [(i, self.ranking[i]) for i in self.shown_ranks(own)]
    if own is None or own not in [i for i, _ in lines]:
      lines.append((None, None)) # the player's own line
    #
    for n, (i, record) in enumerate(lines):
      y = -3.6 - n * LINE
      mine = (record is not None and record.login == login) or record is None
      if mine:
        parts.append(quad(0.4, y + 0.1, 1, width - 0.8, LINE, *ROW_STYLE, action=self.open_action))
      #
      rank = str(i + 1) + '.' if i is not None else '--.'
      time = race_time(record.time) if record is not None else '-:--.--'
      name = record.nickname if record is not None else self.nickname(login)
      color = '$ff0' if i is not None and i < self.top else '$fff'
      parts.append(label(2.6, y - LINE / 2, 2, '$ddd' + rank, 2.4, LINE, size=1, halign='right', valign='center'))
      parts.append(label(2.9, y - LINE / 2, 2, color + time, 4.6, LINE, size=1, valign='center'))
      parts.append(label(7.7, y - LINE / 2, 2, name, width - 8.2, LINE, size=1, valign='center'))
    #
    return frame(''.join(parts), self.widget_x, self.widget_y, 10)
  #

  def nickname(self, login):
    player = self.controller.players.online.get(login)
    return player.nickname if player else login
  #

  async def show(self, login):
    await self.controller.ui.show(self.widget_id, self.render(login), login)
  #

  async def show_all(self):
    for login in list(self.controller.players.online):
      await self.show(login)
    #
  #

  async def player_joined(self, player):
    await self.show(player.login)
  #


  # ---- windows ----

  async def title_clicked(self, login, offset):
    await self.open_window(login)
  #

  async def open_window(self, login):
    rows = [('$ddd' + str(i + 1) + '.', ('$ff0' if i < 3 else '$fff') + race_time(r.time), '$fff' + r.nickname,
      '$ddd' + r.date[:10]) for i, r in enumerate(self.ranking)]
    ranking = list(self.ranking)
    async def show_checkpoints(login, index):
      await self.open_checkpoints(login, ranking[index], index)
    #
    name = strip_colors(self.controller.maps.current['Name']) if self.controller.maps.current else ''
    await self.window.open(login, 'Local Records on ' + name, rows, show_checkpoints, hint='Click a record for its checkpoints')
  #

  async def open_checkpoints(self, login, record, index):
    # the record's checkpoints next to the player's own best run on this map, with the difference
    own = await self.store.best(self.uid, login) if record.login != login else None
    rows, previous = [], 0
    for n, time in enumerate(record.checkpoints):
      name = 'Finish' if n == len(record.checkpoints) - 1 and time == record.time else 'CP ' + str(n + 1)
      if own is None:
        rows.append(('$ddd' + name, '$fff' + race_time(time), '$ddd+' + race_time(time - previous), ''))
      elif n < len(own.checkpoints):
        mine = own.checkpoints[n]
        diff = mine - time
        rows.append(('$ddd' + name, '$fff' + race_time(time), '$fff' + race_time(mine),
          ('$f66+' if diff > 0 else '$6f6-' if diff < 0 else '$ddd±') + difference(abs(diff))))
      else:
        rows.append(('$ddd' + name, '$fff' + race_time(time), '$999-:--.--', ''))
      #
      previous = time
    #
    title = ordinal(index + 1) + ' ' + strip_colors(record.nickname) + ' ' + race_time(record.time)
    if own is not None:
      rows.insert(0, ('', '$999' + strip_colors(record.nickname)[:14], '$999you', '$999you - them'))
    #
    hint = '' if own is not None or record.login == login else 'Drive this map to compare your checkpoints'
    await self.checkpoints_window.open(login, title, rows, hint=hint)
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
