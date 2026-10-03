import asyncio
import os
import urllib.parse

from core import log


TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.dds': 'image/vnd-ms.dds',
  '.gif': 'image/gif'}
DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'www')


class Web:
  # Serves the images manialinks show (the game of every player loads them by URL; the dedicated server can't
  # hand out files). A tiny HTTP server for the files of one directory, nothing else.
  #
  # Settings ([http] in pyseco.toml):
  #   port = 8080                      port to listen on (0: off, then widgets show text instead of images)
  #   url = "http://1.2.3.4:8080"      how the players' games reach that port (public address of the server)
  #   dir = "..."                      directory with the files (default: pyseco's src/www)
  # TM can't load https, so the URL is plain http.

  def __init__(self, controller):
    self.controller = controller
    settings = controller.settings('http')
    self.port = int(settings.get('port', 0))
    self.base_url = str(settings.get('url', '')).strip().rstrip('/')
    self.dir = os.path.abspath(controller.config.path(settings['dir']) if settings.get('dir') else DEFAULT_DIR)
    self.server = None
  #

  def enabled(self):
    return self.port > 0 and bool(self.base_url)
  #

  def url(self, name):
    # the URL of a file the players' games can load, None without web server (or without that file)
    if not self.enabled() or not os.path.isfile(os.path.join(self.dir, name)):
      return None
    #
    return self.base_url + '/' + urllib.parse.quote(name)
  #

  async def start(self):
    if not self.enabled():
      return
    #
    self.server = await asyncio.start_server(self.handle, '0.0.0.0', self.port)
    self.controller.logger.message('[http] Serving ' + self.dir + ' on port ' + str(self.port) + ' as ' + self.base_url,
      log.LOG_INFO)
  #

  async def stop(self):
    if self.server is not None:
      self.server.close()
    #
  #

  async def handle(self, reader, writer):
    try:
      request = (await asyncio.wait_for(reader.readline(), 10)).decode('latin-1').split()
      while (await asyncio.wait_for(reader.readline(), 10)).strip():
        pass
      #
      status, headers, body = self.answer(request)
      head = 'HTTP/1.0 ' + status + '\r\nContent-Length: ' + str(len(body)) + '\r\nConnection: close\r\n'
      writer.write((head + ''.join(k + ': ' + v + '\r\n' for k, v in headers.items()) + '\r\n').encode() + body)
      await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, UnicodeError):
      pass
    finally:
      writer.close()
    #
  #

  def answer(self, request):
    if len(request) < 2 or request[0] not in ('GET', 'HEAD'):
      return '400 Bad Request', {}, b''
    #
    # only files right in the directory: no paths, no hidden files
    name = urllib.parse.unquote(urllib.parse.urlsplit(request[1]).path).lstrip('/')
    path = os.path.join(self.dir, name)
    if not name or '/' in name or '\\' in name or name.startswith('.') or not os.path.isfile(path):
      return '404 Not Found', {}, b''
    #
    with open(path, 'rb') as f:
      body = f.read()
    #
    headers = {'Content-Type': TYPES.get(os.path.splitext(name)[1].lower(), 'application/octet-stream'),
      'Cache-Control': 'max-age=3600'}
    return '200 OK', headers, body if request[0] == 'GET' else b''
  #
#
