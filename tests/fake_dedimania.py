import asyncio
import gzip
import xmlrpc.client


class FakeDedimania:
  # A stand-in for dedimania.net: HTTP POST with an XML-RPC system.multicall.
  # - every call is recorded in self.calls as (method, params), dedimania.Authenticate and WarningsAndTTR too
  # - answers come from self.handlers[method](*params); raising DedimaniaFault makes it a failed call

  def __init__(self, code='secret'):
    self.code = code
    self.calls = []
    self.records = [] # what CurrentChallenge returns: [{'Login', 'NickName', 'Best', 'Checks'}]
    self.handlers = {
      'dedimania.Authenticate': lambda auth: auth['Password'] == self.code,
      'dedimania.ValidateAccount': lambda: {'Status': True, 'Messages': []},
      'dedimania.PlayerArrive': lambda *args: {'Login': args[1], 'MaxRank': 30, 'Status': 0},
      'dedimania.PlayerLeave': lambda game, login: {'Login': login},
      'dedimania.UpdateServerPlayers': lambda *args: True,
      'dedimania.CurrentChallenge': lambda *args: {'Uid': args[0], 'ServerMaxRecords': 30, 'Records': list(self.records)},
      'dedimania.ChallengeRaceTimes': lambda *args: {'Uid': args[0], 'Records': []},
    }
    self.server = None
    self.url = None
  #

  async def start(self):
    self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0)
    self.url = 'http://127.0.0.1:' + str(self.server.sockets[0].getsockname()[1]) + '/Dedimania'
  #

  async def stop(self):
    self.server.close()
    await self.server.wait_closed()
  #

  def called(self, method):
    return [params for name, params in self.calls if name == method]
  #

  async def handle(self, reader, writer):
    headers = {}
    await reader.readline() # POST /Dedimania HTTP/1.1
    while (line := (await reader.readline()).decode().strip()):
      name, _, value = line.partition(':')
      headers[name.lower()] = value.strip()
    #
    body = await reader.readexactly(int(headers['content-length']))
    if headers.get('content-encoding') == 'gzip':
      body = gzip.decompress(body)
    #
    (calls,), _ = xmlrpc.client.loads(body)
    results = []
    for call in calls:
      method, params = call['methodName'], tuple(call['params'])
      self.calls.append((method, params))
      if method == 'dedimania.WarningsAndTTR':
        results.append([{'globalTTR': 0.0, 'methods': []}])
      else:
        results.append([self.handlers[method](*params)])
      #
    #
    answer = xmlrpc.client.dumps((results,), methodresponse=True, allow_none=True).encode()
    writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/xml\r\nContent-Length: ' + str(len(answer)).encode()
      + b'\r\nConnection: close\r\n\r\n' + answer)
    await writer.drain()
    writer.close()
  #
#
