import asyncio
import json
import urllib.parse


def track(track_id, name, uid, unlimiter=None, car=7, primary=0):
  return {'TrackId': track_id, 'TrackName': name, 'UId': uid, 'Authors': [{'User': {'UserId': 1, 'Name': 'author'}}],
    'UnlimiterVersion': unlimiter, 'Environment': 7, 'Car': car, 'PrimaryType': primary, 'AuthorTime': 20000,
    'Awards': 3, 'Tags': [0, 6], 'Difficulty': 1, 'UploadedAt': '2022-07-31T13:01:31',
    'WRReplay': {'ReplayTime': 18670, 'User': {'Name': 'nickie.'}}}
#


class FakeTmx:
  # A stand-in for tmnf.exchange: /api/tracks (by id or uid), /api/replays, /api/meta/tags, /trackrandom, /trackgbx.
  # A downloaded map file is just 'GBX:<uid>' (the fake game server reads the uid from it).

  def __init__(self):
    self.tracks = {} # id -> track
    self.replays = {} # id -> [replay]
    self.random = [] # ids /trackrandom hands out, in order
    self.requests = []
    self.server = None
    self.url = None
  #

  async def start(self):
    self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0)
    self.url = 'http://127.0.0.1:' + str(self.server.sockets[0].getsockname()[1])
  #

  async def stop(self):
    self.server.close()
    await self.server.wait_closed()
  #

  def answer(self, path, query):
    if path == '/api/tracks':
      found = [t for t in self.tracks.values() if str(t['TrackId']) == query.get('id') or t['UId'] == query.get('uid')]
      return 200, {}, json.dumps({'More': False, 'Results': found}).encode()
    #
    if path == '/api/replays':
      return 200, {}, json.dumps({'More': False, 'Results': self.replays.get(int(query['trackId']), [])}).encode()
    #
    if path == '/api/meta/tags':
      return 200, {}, json.dumps([{'Id': 0, 'Name': 'Race'}, {'Id': 6, 'Name': 'LOL'}]).encode()
    #
    if path == '/trackrandom':
      if not self.random:
        return 404, {}, b'not found'
      #
      return 302, {'Location': '/trackshow/' + str(self.random.pop(0))}, b''
    #
    if path.startswith('/trackgbx/'):
      t = self.tracks.get(int(path.rsplit('/', 1)[1]))
      return (200, {}, ('GBX:' + t['UId']).encode()) if t else (404, {}, b'not found')
    #
    return 404, {}, b'not found'
  #

  async def handle(self, reader, writer):
    request = (await reader.readline()).decode().split()
    while (await reader.readline()).strip():
      pass
    #
    parts = urllib.parse.urlsplit(request[1])
    self.requests.append(request[1])
    status, headers, body = self.answer(parts.path, dict(urllib.parse.parse_qsl(parts.query)))
    head = 'HTTP/1.1 ' + str(status) + ' X\r\nContent-Length: ' + str(len(body)) + '\r\nConnection: close\r\n'
    head += ''.join(k + ': ' + v + '\r\n' for k, v in headers.items())
    writer.write(head.encode() + b'\r\n' + body)
    await writer.drain()
    writer.close()
  #
#
