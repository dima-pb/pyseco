import xmlrpc.client

from core import log


# ids of pyseco's manialinks and actions start here, away from the small numbers other tools use
FIRST_MANIALINK_ID = 7100000
FIRST_ACTION = 7100000


def escape(text):
  # for XML attribute values; TM formatting ($f00, $o, ...) stays
  return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
#


def element(name, **attributes):
  # <name a="b" .../>; attributes with value None are left out, a trailing _ is dropped (class_ -> class)
  parts = [name] + [key.rstrip('_') + '="' + escape(value) + '"' for key, value in attributes.items() if value is not None]
  return '<' + ' '.join(parts) + '/>'
#


def frame(content, x=0, y=0, z=0):
  return '<frame posn="' + str(x) + ' ' + str(y) + ' ' + str(z) + '">' + content + '</frame>'
#


def label(x, y, z, text, width=None, height=None, size=2, halign=None, valign=None, action=None):
  return element('label', posn=str(x) + ' ' + str(y) + ' ' + str(z),
    sizen=None if width is None else str(width) + ' ' + str(height or size + 1), text=text, textsize=size,
    halign=halign, valign=valign, action=action)
#


def quad(x, y, z, width, height, style=None, substyle=None, image=None, action=None, url=None):
  return element('quad', posn=str(x) + ' ' + str(y) + ' ' + str(z), sizen=str(width) + ' ' + str(height),
    style=style, substyle=substyle, image=image, action=action, url=url)
#


class UI:
  # Manialinks (the TM UI elements): ids and click actions for everybody who shows something, sending pages,
  # and passing clicks on to the handler that registered the action.
  #
  # Coordinates (posn/sizen) go from x -64 (left) to 64 (right) and y 48 (top) to -48 (bottom).
  # services/windows.py builds windows and widgets on top of this.

  def __init__(self, controller):
    self.controller = controller
    self.next_manialink_id = FIRST_MANIALINK_ID
    self.next_action = FIRST_ACTION
    self.action_blocks = [] # (first action, count, handler(login, offset))
    # a player sees one window at a time: all windows share this manialink id, opening one replaces the other
    self.window_id = self.manialink_id()
    self.open_windows = {} # login -> the window the player sees
    controller.events.register('TrackMania.PlayerManialinkPageAnswer', self.page_answer)
  #

  def manialink_id(self):
    # a new id; showing a page with the same id again replaces it
    self.next_manialink_id += 1
    return str(self.next_manialink_id - 1)
  #

  def actions(self, count, handler):
    # reserves count actions, returns the first; a click on first + n calls await handler(login, n)
    first = self.next_action
    self.next_action += count
    self.action_blocks.append((first, count, handler))
    return first
  #

  async def show(self, manialink_id, content, login=None):
    # to this player (or a comma-separated list of logins), to everybody without login
    xml = ('<?xml version="1.0" encoding="UTF-8"?><manialinks><manialink id="' + manialink_id + '">' + content
      + '</manialink></manialinks>')
    try:
      if login is None:
        await self.controller.server.send_display_manialink_page(xml, 0, False)
      else:
        await self.controller.server.send_display_manialink_page_to_login(login, xml, 0, False)
      #
    except (xmlrpc.client.Fault, ConnectionError) as exc:
      self.controller.logger.message('Manialink ' + manialink_id + ' could not be shown: ' + str(exc), log.LOG_WARNING)
    #
  #

  async def hide(self, manialink_id, login=None):
    await self.show(manialink_id, '', login)
  #

  def window_opened(self, login, window):
    previous = self.open_windows.get(login)
    if previous is not None and previous is not window:
      previous.forget(login)
    #
    self.open_windows[login] = window
  #

  def window_closed(self, login, window):
    if self.open_windows.get(login) is window:
      del self.open_windows[login]
    #
  #

  async def page_answer(self, params):
    login, answer = params[1], params[2]
    for first, count, handler in self.action_blocks:
      if first <= answer < first + count:
        await handler(login, answer - first)
        return
      #
    #
  #
#
