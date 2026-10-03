import asyncio
import socket
import urllib.error
import urllib.request

from conftest import Harness


def run(coro):
  return asyncio.run(coro)
#


def free_port():
  with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    return sock.getsockname()[1]
  #
#


def fetch(url):
  try:
    with urllib.request.urlopen(url, timeout=5) as response:
      return response.status, response.headers.get('Content-Type'), response.read()
    #
  except urllib.error.HTTPError as error:
    return error.code, None, b''
  #
#


def test_images_are_served_and_nothing_else(tmp_path):
  async def scenario():
    port = free_port()
    config = '[http]\nport = ' + str(port) + '\nurl = "http://example.org:9999"\n'
    async with Harness(tmp_path, config) as h:
      web = h.controller.web
      assert web.url('discord.png') == 'http://example.org:9999/discord.png'
      assert web.url('missing.png') is None
      base = 'http://127.0.0.1:' + str(port) + '/'
      status, kind, body = await asyncio.to_thread(fetch, base + 'discord.png')
      assert (status, kind) == (200, 'image/png') and body.startswith(b'\x89PNG')
      for path in ('', 'missing.png', '../core/config.py', '..%2fcore%2fconfig.py', '%2e%2e/pyseco.py', '.hidden'):
        assert (await asyncio.to_thread(fetch, base + path))[0] == 404, path
      #
    #
  #
  run(scenario())
#


def test_without_web_server_widgets_get_no_urls(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      assert not h.controller.web.enabled() and h.controller.web.url('discord.png') is None
    #
  #
  run(scenario())
#
