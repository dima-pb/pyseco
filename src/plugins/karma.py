from core import commands, events
from core.text import strip_colors
from plugins.plugin import Plugin
from services.karma import percent, text
from services.ui import frame, label, quad
from services.windows import ROW_STYLE, TITLE_STYLE, WINDOW_STYLE, ListWindow


# as wide as the game's ranking box above it
WIDTH, HEIGHT = 13, 7.4
VOTES = {'++': 1, '--': -1}


class Karma(Plugin):
  # Players rate the current map: ++ or -- in the chat (with or without /), or a click in the widget; a click on
  # the own vote takes it back. The widget shows the votes of the map and the player's own; /karma shows who voted
  # how.
  # The widget is "karma", it can be moved with [widgets.karma].

  def __init__(self, controller):
    super().__init__(controller)
    ui = controller.ui
    self.id = ui.manialink_id()
    # at the left, below the Discord button, lined up with the game's ranking box
    self.x, self.y = ui.position('karma', -64, 22.4)
    self.first_action = ui.actions(3, self.clicked) # ++, --, the title (opens /karma)
    self.window = ListWindow(ui, width=70, columns=[10, 40, 16])
    self.uid = None
    self.votes = {} # login -> 1 or -1 on the current map

    controller.events.register(events.MAP_STARTED, self.map_started)
    controller.events.register(events.PLAYER_JOINED, self.player_joined)
    controller.events.register(events.CHAT, self.chat)
    controller.events.register(events.KARMA_CHANGED, self.changed)
    register = controller.commands.register
    register('++', self.cmd_good, help='rates this map as good', sources=(commands.GAME,))
    register('--', self.cmd_bad, help='rates this map as bad', sources=(commands.GAME,))
    register('karma', self.cmd_karma, help='shows how this map was rated')
  #

  async def start(self):
    if self.controller.maps.current is not None:
      await self.map_started(self.controller.maps.current)
    #
  #

  async def stop(self):
    await self.controller.ui.hide(self.id)
  #

  def counts(self):
    return sum(1 for v in self.votes.values() if v > 0), sum(1 for v in self.votes.values() if v < 0)
  #


  # ---- voting ----

  async def vote(self, login, value):
    if self.uid is None:
      return
    #
    if self.votes.get(login) == value:
      await self.controller.chat.tell(login, 'You rated this map ' + ('++' if value > 0 else '--') + ' already.')
      return
    #
    await self.controller.karma.vote(self.uid, login, value) # raises KARMA_CHANGED: changed() shows it
    await self.controller.chat.tell(login, 'You rated this map ' + ('$0f0++' if value > 0 else '$f44--') + '$z$s.')
  #

  async def chat(self, message):
    if message.text in VOTES:
      await self.vote(message.player.login, VOTES[message.text])
    #
  #

  async def cmd_good(self, ctx):
    await self.vote(ctx.login, 1)
  #

  async def cmd_bad(self, ctx):
    await self.vote(ctx.login, -1)
  #

  async def clicked(self, login, offset):
    value = 1 if offset == 0 else -1
    if offset == 2:
      await self.open_window(login)
    elif self.uid is not None and self.votes.get(login) == value:
      await self.controller.karma.unvote(self.uid, login) # a click on the own vote takes it back
      await self.controller.chat.tell(login, 'Your rating of this map is taken back.')
    else:
      await self.vote(login, value)
    #
  #


  # ---- what the widget shows ----

  async def map_started(self, map):
    self.uid = map['UId']
    self.votes = await self.controller.karma.votes(self.uid)
    await self.show_all()
  #

  async def changed(self, uid):
    if uid == self.uid:
      self.votes = await self.controller.karma.votes(uid)
      await self.show_all()
    #
  #

  async def player_joined(self, player):
    await self.show(player.login)
  #

  async def show_all(self):
    for login in list(self.controller.players.online):
      await self.show(login)
    #
  #

  async def show(self, login):
    plus, minus = self.counts()
    share = percent(plus, minus)
    own = self.votes.get(login)
    action = lambda offset: self.first_action + offset
    parts = [quad(0, 0, 0, WIDTH, HEIGHT, *WINDOW_STYLE, action=action(2)),
      quad(0.4, -0.4, 1, WIDTH - 0.8, 2.4, *TITLE_STYLE, action=action(2)),
      label(1, -1.6, 2, '$fffKarma', WIDTH - 2, 2, size=1, valign='center'),
      label(WIDTH / 2, -3.85, 2, ('$fff' + str(share) + '%  ' + text(plus, minus)) if share is not None else '$999no votes yet',
        WIDTH - 1, 2, size=1, halign='center', valign='center')]
    button = (WIDTH - 1.4) / 2
    for n, (word, value) in enumerate(VOTES.items()):
      x = 0.5 + n * (button + 0.4)
      # the own vote stands out: orange, the other one in the row style
      parts.append(quad(x, -4.9, 2, button, 2.1, *(TITLE_STYLE if own == value else ROW_STYLE), action=action(n)))
      parts.append(label(x + button / 2, -5.95, 3, ('$0f0' if value > 0 else '$f44') + word, button - 0.4, 1.8, size=1,
        halign='center', valign='center'))
    #
    await self.controller.ui.show(self.id, frame(''.join(parts), self.x, self.y, 10), login)
  #

  async def open_window(self, login):
    if self.uid is None:
      return
    #
    plus, minus = self.counts()
    names = {}
    for voter in self.votes:
      stored = await self.controller.storage.players.get(voter)
      names[voter] = stored.nickname if stored and stored.nickname else voter
    #
    rows = [('$0f0++' if value > 0 else '$f44--', '$fff' + names[voter], '$ddd' + voter)
      for voter, value in sorted(self.votes.items(), key=lambda item: (-item[1], strip_colors(names[item[0]]).lower()))]
    name = strip_colors(self.controller.maps.current['Name']) if self.controller.maps.current else ''
    share = percent(plus, minus)
    await self.window.open(login, 'Karma of ' + name + (': ' + str(share) + '%' if share is not None else ''), rows,
      hint='Vote with ++ or -- in the chat')
  #

  async def cmd_karma(self, ctx):
    if ctx.source == commands.GAME:
      await self.open_window(ctx.login)
      return
    #
    plus, minus = self.counts()
    share = percent(plus, minus)
    await ctx.reply('No votes on this map yet.' if share is None else
      'Karma of this map: ' + str(share) + '% (' + str(plus) + ' good, ' + str(minus) + ' bad)')
  #
#
