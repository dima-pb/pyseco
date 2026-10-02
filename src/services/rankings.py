from core.text import strip_colors
from services.ui import frame, label, quad
from services.windows import ROW_STYLE, TITLE_STYLE, WINDOW_STYLE, ListWindow


# Widget and windows for a ranking of times (local records, Dedimania, ...). A ranking is a list, best first,
# of objects with login, nickname, time (ms) and checkpoints ([ms]).


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
WIDTH = 16


class RankingWidget:
  # Shows every player the top records, the one to beat and their own, and the last place (the time it takes to
  # get in); a click anywhere on it opens the whole ranking (RankingWindows).
  #   widget = RankingWidget(controller.ui, 'local_records', 'Local Records', x, y, top, on_click)
  #   await widget.show(login, nickname, ranking)
  # on_click(login) is awaited on a click. The place can be moved with [widgets.<name>].

  def __init__(self, ui, name, title, x, y, top, on_click):
    self.ui = ui
    self.title = title
    self.top = max(top, 1)
    self.lines = self.top + 3 # the one to beat, the own, the last
    self.id = ui.manialink_id()
    self.x, self.y = ui.position(name, x, y)
    self.action = ui.actions(1, lambda login, offset: on_click(login))
  #

  def shown_ranks(self, ranking, own):
    # positions in the ranking the widget shows: the top, the one to beat and the own record, the last one
    count = len(ranking)
    ranks = list(range(min(self.top, count)))
    if own is not None and own >= self.top:
      ranks += [rank for rank in (own - 1, own) if rank >= self.top]
    #
    if count > self.top and count - 1 not in ranks:
      ranks.append(count - 1)
    #
    return ranks
  #

  def render(self, login, nickname, ranking):
    own = next((i for i, r in enumerate(ranking) if r.login == login), None)
    height = 3.6 + self.lines * LINE + 0.8
    # everything is clickable, it opens the whole ranking
    parts = [quad(0, 0, 0, WIDTH, height, *WINDOW_STYLE, action=self.action),
      quad(0.4, -0.4, 1, WIDTH - 0.8, 2.8, *TITLE_STYLE, action=self.action),
      label(1, -1.8, 2, '$fff' + self.title, WIDTH - 2, 2, size=1, valign='center')]
    lines = [(i, ranking[i]) for i in self.shown_ranks(ranking, own)]
    if own is None:
      lines.append((None, None)) # the player's own line
    #
    previous = -1
    for n, (i, record) in enumerate(lines):
      if i is not None and i > previous + 1 and n > 0:
        # a gap in the ranks: a thin line between
        parts.append(quad(2, -3.6 - n * LINE + 0.15, 1, WIDTH - 4, 0.15, *ROW_STYLE))
      #
      previous = i if i is not None else previous
      y = -3.6 - n * LINE
      if record is None or record.login == login:
        parts.append(quad(0.4, y + 0.1, 1, WIDTH - 0.8, LINE, *ROW_STYLE, action=self.action))
      #
      rank = str(i + 1) + '.' if i is not None else '--.'
      time = race_time(record.time) if record is not None else '-:--.--'
      name = record.nickname if record is not None else nickname
      color = '$ff0' if i is not None and i < self.top else '$fff'
      parts.append(label(2.6, y - LINE / 2, 2, '$ddd' + rank, 2.4, LINE, size=1, halign='right', valign='center'))
      parts.append(label(2.9, y - LINE / 2, 2, color + time, 4.6, LINE, size=1, valign='center'))
      parts.append(label(7.7, y - LINE / 2, 2, name, WIDTH - 8.2, LINE, size=1, valign='center'))
    #
    return frame(''.join(parts), self.x, self.y, 10)
  #

  async def show(self, login, nickname, ranking):
    await self.ui.show(self.id, self.render(login, nickname, ranking), login)
  #

  async def hide(self, login=None):
    await self.ui.hide(self.id, login)
  #
#


class RankingWindows:
  # The whole ranking in a window; a click on a record compares its checkpoints with the player's own run.

  def __init__(self, ui):
    self.window = ListWindow(ui, width=90, columns=[7, 14, 46, 19])
    self.checkpoints_window = ListWindow(ui, width=70, page_size=20, columns=[12, 18, 18, 18])
  #

  async def open(self, login, title, ranking, own, dates=True):
    # own: the player's own best run (with checkpoints) to compare with, or None
    rows = [('$ddd' + str(i + 1) + '.', ('$ff0' if i < 3 else '$fff') + race_time(r.time), '$fff' + r.nickname,
      '$ddd' + (r.date[:10] if dates and getattr(r, 'date', None) else '')) for i, r in enumerate(ranking)]
    ranking = list(ranking)
    async def show_checkpoints(login, index):
      await self.open_checkpoints(login, ranking[index], index, own)
    #
    await self.window.open(login, title, rows, show_checkpoints, hint='Click a record for its checkpoints')
  #

  async def open_checkpoints(self, login, record, index, own):
    # the record's checkpoints next to the player's own best run, with the difference
    if own is not None and own.login == record.login:
      own = None
    #
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
#
