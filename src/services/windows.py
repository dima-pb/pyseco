from core import events
from services.ui import frame, label, quad


# look of windows, in one place to adjust it
WINDOW_STYLE = ('Bgs1', 'BgWindow3')
WINDOW_LAYERS = 1 # the background drawn this many times on top of each other: less see-through
TITLE_STYLE = ('Bgs1InRace', 'BgTitle3_1')
ROW_STYLE = ('BgsPlayerCard', 'BgCardSystem') # every row; one of the few styles that light up under the mouse when clickable
ICONS = 'Icons64x64_1'
HINT_COLOR = '$bbb'

ROW_HEIGHT = 3.4
TEXT_SIZE = 2
TOP = 7.5     # title bar and space below it
BOTTOM = 2.5  # space below the rows without footer
FOOTER = 6    # page arrows and hint


class ListWindow:
  # A window with a title and a list of rows, page by page. Every player has their own content and page,
  # and sees one window at a time: opening another window replaces this one.
  #
  #   window = ListWindow(controller.ui)                  in the plugin's __init__
  #   await window.open(login, 'Title', rows, on_click, hint='Click a map to wish it')
  #     rows: [str] or [(column, column, ...)]
  #
  # on_click(login, index) is awaited when the player clicks a row (index in rows); without it the
  # rows are not clickable. columns: widths of the columns, they must add up to at most width - 4.

  def __init__(self, ui, width=80, page_size=15, columns=None):
    self.ui = ui
    self.width = width
    self.page_size = page_size
    self.columns = columns or [width - 4]
    # actions: one per row on a page, then close, previous and next page
    self.first_action = ui.actions(page_size + 3, self.clicked)
    self.close_action = page_size
    self.prev_action = page_size + 1
    self.next_action = page_size + 2
    self.open_for = {} # login -> {'title', 'rows', 'page', 'on_click', 'hint'}
    ui.controller.events.register(events.PLAYER_LEFT, self.player_left)
  #

  def pages(self, rows):
    return max(1, (len(rows) + self.page_size - 1) // self.page_size)
  #

  async def open(self, login, title, rows, on_click=None, page=0, hint=''):
    rows = [row if isinstance(row, (tuple, list)) else (row,) for row in rows]
    page = min(max(page, 0), self.pages(rows) - 1)
    self.ui.window_opened(login, self)
    self.open_for[login] = {'title': title, 'rows': rows, 'page': page, 'on_click': on_click, 'hint': hint}
    await self.ui.show(self.ui.window_id, self.render(self.open_for[login]), login)
  #

  async def close(self, login):
    if self.open_for.pop(login, None) is not None:
      self.ui.window_closed(login, self)
      await self.ui.hide(self.ui.window_id, login)
    #
  #

  def forget(self, login):
    # another window replaced this one
    self.open_for.pop(login, None)
  #

  def is_open(self, login):
    return login in self.open_for
  #

  def render(self, state):
    rows, page = state['rows'], state['page']
    pages = self.pages(rows)
    shown = rows[page * self.page_size:(page + 1) * self.page_size]
    # as high as needed; with several pages always as high as a full page, so the arrows stay in place
    lines = self.page_size if pages > 1 else max(len(shown), 1)
    footer = pages > 1 or state['hint']
    width = self.width
    height = TOP + lines * ROW_HEIGHT + (FOOTER if footer else BOTTOM)
    action = lambda offset: self.first_action + offset
    parts = [quad(0, 0, 0, width, height, *WINDOW_STYLE) for _ in range(WINDOW_LAYERS)]
    parts += [
      quad(1, -1, 1, width - 2, 4.5, *TITLE_STYLE),
      label(3, -3.25, 2, '$fff' + state['title'], width - 10, 3, size=3, valign='center'),
      quad(width - 5.5, -1.4, 3, 3.6, 3.6, ICONS, 'Close', action=action(self.close_action)),
    ]
    for i, row in enumerate(shown):
      top = -TOP - i * ROW_HEIGHT
      clickable = state['on_click'] is not None
      parts.append(quad(1.5, top, 1, width - 3, ROW_HEIGHT - 0.2, *ROW_STYLE, action=action(i) if clickable else None))
      x = 2.5
      for column, text in zip(self.columns, row):
        parts.append(label(x, top - ROW_HEIGHT / 2, 2, text, column - 1, ROW_HEIGHT - 0.4, size=TEXT_SIZE,
          valign='center'))
        x += column
      #
    #
    if not rows:
      parts.append(label(2.5, -TOP - ROW_HEIGHT / 2, 2, '$999(empty)', width - 5, ROW_HEIGHT - 0.4, valign='center'))
    #
    if footer:
      middle = -height + FOOTER / 2 + 0.5
      if state['hint']:
        parts.append(label(3, middle, 2, HINT_COLOR + state['hint'], width / 2 - 18, 3, valign='center'))
      #
      if pages > 1:
        parts.append(label(width - 14, middle, 2, '$fff' + str(page + 1) + ' / ' + str(pages), size=2,
          halign='center', valign='center'))
        if page > 0:
          parts.append(quad(width - 22, middle + 1.8, 2, 3.6, 3.6, ICONS, 'ArrowPrev', action=action(self.prev_action)))
        #
        if page < pages - 1:
          parts.append(quad(width - 9.6, middle + 1.8, 2, 3.6, 3.6, ICONS, 'ArrowNext', action=action(self.next_action)))
        #
      #
    #
    # centered on the screen, above the race UI
    return frame(''.join(parts), -width / 2, height / 2, 20)
  #

  async def clicked(self, login, offset):
    state = self.open_for.get(login)
    if state is None: # e.g. pyseco restarted while the window was open
      await self.ui.hide(self.ui.window_id, login)
      return
    #
    if offset == self.close_action:
      await self.close(login)
    elif offset in (self.prev_action, self.next_action):
      state['page'] += -1 if offset == self.prev_action else 1
      await self.open(login, state['title'], state['rows'], state['on_click'], state['page'], state['hint'])
    elif state['on_click'] is not None:
      index = state['page'] * self.page_size + offset
      if index < len(state['rows']):
        await state['on_click'](login, index)
      #
    #
  #

  async def player_left(self, player):
    if self.open_for.pop(player.login, None) is not None:
      self.ui.window_closed(player.login, self)
    #
  #
#


class TextWidget:
  # Text at a fixed place on the screen, e.g. a clock:
  #   widget = TextWidget(controller.ui, x=50, y=40)
  #   await widget.show('12:00')            to everybody; show(text, login) to one player
  # With background=False only the text is shown.

  def __init__(self, ui, x, y, width=14, height=4, size=2, background=True):
    self.ui = ui
    self.x, self.y, self.width, self.height, self.size = x, y, width, height, size
    self.background = background
    self.id = ui.manialink_id()
  #

  async def show(self, text, login=None):
    parts = [quad(0, 0, 0, self.width, self.height, *WINDOW_STYLE) for _ in range(WINDOW_LAYERS)] if self.background else []
    parts.append(label(self.width / 2, -self.height / 2, 1, text, self.width - 1, self.height - 1, size=self.size,
      halign='center', valign='center'))
    await self.ui.show(self.id, frame(''.join(parts), self.x, self.y, 10), login)
  #

  async def hide(self, login=None):
    await self.ui.hide(self.id, login)
  #
#
