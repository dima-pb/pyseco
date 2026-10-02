import asyncio
import struct
import xmlrpc.client


class FakeServer:
  # A stand-in for the dedicated server's XML-RPC interface (GBXRemote 2) for tests.
  #
  # - every request is recorded in self.calls as (method, params)
  # - answers come from self.handlers[method](*params); a handler may raise xmlrpc.client.Fault.
  #   Unknown methods answer True, so tests only define what they care about
  # - await callback(method, *params) sends a callback to the connected controller

  def __init__(self, password='SuperAdmin'):
    self.password = password
    self.calls = []
    # a small map list: current map, next map (ChooseNextChallenge), add/remove, like the real server
    self.maps = [self.make_map(i) for i in range(1, 6)]
    self.current = 0
    self.next = 1
    self.refuse = set() # file names CheckChallengeForCurrentServerParams refuses
    self.players = {} # login -> PlayerInfo of the players on the server
    self.handlers = {
      'Authenticate': self.authenticate,
      'GetPlayerList': lambda *args: [dict(p) for p in self.players.values()],
      'GetPlayerInfo': self.player_info,
      'GetChallengeList': lambda count, start: [dict(m) for m in self.maps[start:start + count]],
      'GetCurrentChallengeInfo': lambda: dict(self.maps[self.current]),
      'GetNextChallengeInfo': lambda: dict(self.maps[self.next]),
      'ChooseNextChallenge': self.choose_next,
      'CheckChallengeForCurrentServerParams': self.check_map,
      'AddChallenge': self.add_map,
      'RemoveChallenge': self.remove_map,
      'Echo': self.echo,
    }
    self.writer = None
    self.connected = asyncio.Event()
    self.server = None
    self.port = None
  #

  async def start(self, port=0):
    self.server = await asyncio.start_server(self.handle, '127.0.0.1', port)
    self.port = self.server.sockets[0].getsockname()[1]
  #

  async def stop(self):
    if self.writer is not None:
      self.writer.close()
    #
    self.server.close()
    await self.server.wait_closed()
  #

  def authenticate(self, login, password):
    if login != 'SuperAdmin' or password != self.password:
      raise xmlrpc.client.Fault(-1000, 'Password incorrect.')
    #
    return True
  #

  def player_info(self, login, version=1):
    if login not in self.players:
      raise xmlrpc.client.Fault(-1000, 'Login unknown.')
    #
    return dict(self.players[login])
  #

  @staticmethod
  def make_map(i, prefix='Map'):
    return {'UId': 'uid' + str(i), 'Name': '$f00' + prefix + ' ' + str(i), 'FileName': 'Challenges\\' + prefix + str(i) + '.Challenge.Gbx',
      'Author': 'author' + str(i), 'Environnement': 'Stadium', 'GoldTime': 30000, 'CopperPrice': 100}
  #

  def index(self, filename):
    for i, m in enumerate(self.maps):
      if m['FileName'] == filename:
        return i
      #
    #
    raise xmlrpc.client.Fault(-1000, 'Challenge not found.')
  #

  def choose_next(self, filename):
    self.next = self.index(filename)
    return True
  #

  def check_map(self, filename):
    if filename in self.refuse:
      raise xmlrpc.client.Fault(-1000, 'Wrong environment.')
    #
    return True
  #

  def add_map(self, filename):
    self.maps.append(self.make_map(len(self.maps) + 100, 'Added') | {'FileName': filename,
      'UId': 'uid-' + filename})
    self.list_modified()
    return True
  #

  def remove_map(self, filename):
    i = self.index(filename)
    del self.maps[i]
    if i < self.current:
      self.current -= 1
    #
    self.list_modified()
    return True
  #

  def list_modified(self):
    asyncio.get_running_loop().create_task(
      self.callback('TrackMania.ChallengeListModified', self.current, self.next, True))
  #

  def echo(self, first, second):
    # the real server swaps the parameters in the callback
    asyncio.get_running_loop().create_task(self.callback('TrackMania.Echo', second, first))
    return True
  #

  async def play_next(self):
    # the server switches to the next map: EndRace, then BeginChallenge of the next map
    self.current = self.next
    self.next = (self.current + 1) % len(self.maps)
    await self.callback('TrackMania.BeginChallenge', dict(self.maps[self.current]), False, False)
  #

  def called(self, method):
    return [params for name, params in self.calls if name == method]
  #

  async def handle(self, reader, writer):
    self.writer = writer
    header = b'GBXRemote 2'
    writer.write(struct.pack('<I', len(header)) + header)
    self.connected.set()
    try:
      while True:
        size, handle = struct.unpack('<II', await reader.readexactly(8))
        params, method = xmlrpc.client.loads((await reader.readexactly(size)).decode())
        self.calls.append((method, params))
        try:
          result = self.handlers.get(method, lambda *args: True)(*params)
          body = xmlrpc.client.dumps((result,), methodresponse=True)
        except xmlrpc.client.Fault as fault:
          body = xmlrpc.client.dumps(fault)
        #
        self.send(handle, body)
      #
    except (asyncio.IncompleteReadError, ConnectionError):
      pass
    #
  #

  def send(self, handle, body):
    data = body.encode()
    self.writer.write(struct.pack('<II', len(data), handle) + data)
  #

  async def callback(self, method, *params):
    self.send(0x1, xmlrpc.client.dumps(params, method))
    await self.writer.drain()
  #
#
