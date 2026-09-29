import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

import config
import log
import pyseco
from fake_server import FakeServer


def write_config(tmp_path, port, extra=''):
  path = tmp_path / 'pyseco.toml'
  path.write_text(
    '[server]\nhost = "127.0.0.1"\nport = ' + str(port) + '\npassword = "SuperAdmin"\n'
    '[controller]\nmasteradmins = ["master"]\nplugins = []\nlog_level = "error"\n' + extra)
  return str(path)
#


class Harness:
  # a controller connected to a FakeServer, running in the background

  def __init__(self, tmp_path, extra_config=''):
    self.tmp_path = tmp_path
    self.extra_config = extra_config
  #

  async def __aenter__(self):
    self.server = FakeServer()
    await self.server.start()
    cfg = config.Config(write_config(self.tmp_path, self.server.port, self.extra_config))
    self.controller = pyseco.TMController(cfg, log.Logging(cfg.log_path, cfg.log_level))
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
#
