from core import commands, events, roles
from core.text import strip_colors
from plugins.plugin import Plugin
from services.ui import frame, label, quad
from services.windows import ROW_STYLE, ListWindow


# (admin action, button text); buttons for actions the player's role allows
BUTTONS = [('next', 'Next'), ('replay', 'Replay'), ('restart', 'Restart'), ('remove', 'Remove')]
# actions that ask first: the question, the answer that does it
CONFIRM = {
  'next': ('Skip to the next map?', 'Yes, next map'),
  'restart': ('Restart {map}?', 'Yes, restart it'),
  'remove': ('Remove {map}?', 'Yes, remove it from the map list'),
}
WIDTH, HEIGHT, GAP = 6, 1.8, 0.4


class AdminPanel(Plugin):
  # Buttons for operators and admins at the bottom left (next map, replay, restart, remove the map); they run
  # the same /admin actions. Next, restart and remove ask first.
  # The panel is the widget "admin_panel", it can be moved with [widgets.admin_panel].

  def __init__(self, controller):
    super().__init__(controller)
    ui = controller.ui
    self.id = ui.manialink_id()
    # below the chat, at the bottom of the screen, right of the chat's scroll buttons
    self.x, self.y = ui.position('admin_panel', -61.3, -45.9)
    self.first_action = ui.actions(len(BUTTONS), self.clicked)
    self.confirm_window = ListWindow(ui, width=60, page_size=2)
    controller.events.register(events.PLAYER_JOINED, self.player_joined)
    controller.events.register(events.ROLE_CHANGED, self.role_changed)
  #

  async def start(self):
    for player in list(self.controller.players.online.values()):
      await self.show(player.login)
    #
  #

  async def stop(self):
    await self.controller.ui.hide(self.id)
  #

  def buttons(self, role):
    allowed = {a.name for a in self.controller.admin.available(role)}
    return [(i, text) for i, (action, text) in enumerate(BUTTONS) if action in allowed]
  #

  async def show(self, login):
    role = await self.controller.accounts.role(login)
    buttons = self.buttons(role) if role >= roles.OPERATOR else []
    if not buttons:
      await self.controller.ui.hide(self.id, login)
      return
    #
    parts = []
    for n, (i, text) in enumerate(buttons):
      x = n * (WIDTH + GAP)
      parts.append(quad(x, 0, 0, WIDTH, HEIGHT, *ROW_STYLE, action=self.first_action + i))
      parts.append(label(x + WIDTH / 2, -HEIGHT / 2, 1, '$fff' + text, WIDTH - 0.6, HEIGHT - 0.4, size=1,
        halign='center', valign='center'))
    #
    await self.controller.ui.show(self.id, frame(''.join(parts), self.x, self.y, 10), login)
  #

  async def player_joined(self, player):
    await self.show(player.login)
  #

  async def role_changed(self, login):
    if login in self.controller.players.online:
      await self.show(login)
    #
  #

  async def context(self, login):
    player = self.controller.players.online.get(login)
    return commands.Context(commands.GAME, login, player.nickname if player else login,
      await self.controller.accounts.role(login), [], lambda text: self.controller.chat.tell(login, text))
  #

  async def clicked(self, login, offset):
    action = BUTTONS[offset][0]
    if action not in CONFIRM:
      await self.controller.admin.run(await self.context(login), action)
      return
    #
    current = self.controller.maps.current
    if current is None:
      return
    #
    async def answer(login, index):
      await self.confirm_window.close(login)
      if index == 0 and self.controller.maps.current is current: # still the same map
        await self.controller.admin.run(await self.context(login), action)
      #
    #
    question, yes = CONFIRM[action]
    await self.confirm_window.open(login, question.format(map=strip_colors(current['Name'])), ['$fff' + yes, '$fffNo'],
      answer, hint='The file stays on the server' if action == 'remove' else '')
  #
#
