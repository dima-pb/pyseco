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
    self.handlers = {
      'Authenticate': self.authenticate,
      'GetPlayerList': lambda *args: [],
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
