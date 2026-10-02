import asyncio
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

from core import config, log
from core.controller import Controller
from fake_server import FakeServer


def write_config(tmp_path, port, extra='', plugins=()):
  path = tmp_path / 'pyseco.toml'
  path.write_text(
    '[server]\nhost = "127.0.0.1"\nport = ' + str(port) + '\npassword = "SuperAdmin"\n'
    '[controller]\nmasteradmins = ["master"]\nplugins = [' + ', '.join('"' + p + '"' for p in plugins) + ']\n'
    'log_level = "error"\n' + extra)
  return str(path)
#


class Harness:
  # a controller connected to a FakeServer, running in the background

  def __init__(self, tmp_path, extra_config='', plugins=(), server=None):
    self.tmp_path = tmp_path
    self.extra_config = extra_config
    self.plugins = plugins
    self.server = server # reuse a FakeServer (its map state) across controller restarts
  #

  async def __aenter__(self):
    if self.server is None:
      self.server = FakeServer()
    #
    self.server.connected.clear()
    await self.server.start()
    cfg = config.Config(write_config(self.tmp_path, self.server.port, self.extra_config, self.plugins))
    self.controller = Controller(cfg, log.Logging(cfg.log_path, cfg.log_level))
    self.task = asyncio.create_task(self.controller.run())
    await asyncio.wait_for(self.server.connected.wait(), 5)
    await self.settle()
    return self
  #

  async def __aexit__(self, *exc):
    await self.controller.stop()
    await asyncio.wait_for(self.task, 5)
    await self.server.stop()
  #

  async def settle(self, seconds=0.2):
    # lets the controller process what the fake server sent
    await asyncio.sleep(seconds)
  #

  async def chat(self, login, text, uid=5):
    await self.server.callback('TrackMania.PlayerChat', uid, login, text, text.startswith('/'))
    await self.settle()
  #

  def replies_to(self, login):
    return [params[0] for params in self.server.called('ChatSendServerMessageToLogin') if params[1] == login]
  #

  def announcements(self):
    return [params[0] for params in self.server.called('ChatSendServerMessage')]
  #

  def plugin(self, name):
    return self.controller.plugins.get(name)
  #

  def manialink(self, login, manialink_id=None):
    # the last manialink (an ElementTree element) shown to this player, None if it was hidden since
    shown = [params[1] for params in self.server.called('SendDisplayManialinkPageToLogin') if params[0] == login]
    for xml in reversed(shown):
      page = ET.fromstring(xml).find('manialink')
      if manialink_id is None or page.get('id') == manialink_id:
        return page if len(page) else None
      #
    #
    return None
  #

  async def click(self, login, action, uid=5):
    await self.server.callback('TrackMania.PlayerManialinkPageAnswer', uid, login, int(action))
    await self.settle()
  #
#


def texts(page):
  # the texts of all labels in a manialink
  return [l.get('text') for l in page.iter('label')]
#


def action_of(page, text):
  # the action of the clickable row that contains the label with this text (or of the icon with this substyle)
  for f in page.iter('frame'):
    elements = list(f)
    for i, e in enumerate(elements):
      if e.tag == 'quad' and e.get('substyle') == text:
        return e.get('action')
      #
      if e.tag == 'label' and e.get('text') == text:
        row = [q for q in elements[:i] if q.tag == 'quad' and q.get('action')]
        return row[-1].get('action')
      #
    #
  #
  raise AssertionError(text + ' not found')
#
