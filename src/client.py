import asyncio

import messages


class TMClient:
  # GBXRemote connection to the dedicated server.
  #
  # A single reader task (read_loop) owns the socket's read side. Every incoming message is either
  # - a response: its handle has the high bit set and belongs to a request we sent -> it resolves
  #   the future that send() is awaiting, or
  # - a callback: handed to on_callback, which just queues it for the controller.
  # So send() can simply await its response while callbacks keep flowing, without any polling.

  def __init__(self, url, port, on_callback):
    self.supported_protocols = ['GBXRemote 2']
    self.url = url
    self.port = port
    self.on_callback = on_callback # called with the xml of every callback, must not block
    self.reader = None
    self.writer = None
    self.read_task = None
    self.pending = {} # request handle -> future that receives the response xml
    self.req_handle = 0x80000000
  #

  async def connect(self):
    self.reader, self.writer = await asyncio.open_connection(self.url, self.port)

    size = int.from_bytes(await self.reader.readexactly(4), 'little')
    protocol = (await self.reader.readexactly(size)).decode('utf-8')
    if protocol not in self.supported_protocols:
      raise ValueError('Unsupported protocol ' + protocol)
    #

    self.read_task = asyncio.create_task(self.read_loop())

    if not await self.send(messages.EnableCallbacks()):
      raise Exception('Unable to enable callbacks')
    #
  #

  async def send(self, msg):
    if self.read_task is None or self.read_task.done():
      raise ConnectionError('Not connected to the server')
    #

    handle = self.req_handle
    self.req_handle = self.req_handle + 1 if self.req_handle < 0xFFFFFFFF else 0x80000000

    response = asyncio.get_running_loop().create_future()
    self.pending[handle] = response
    self.writer.write(msg.serialize(handle))
    await self.writer.drain()

    # suspends only this caller until read_loop delivers the response, everything else keeps running
    return msg.parse_response(await response)
  #

  async def read_loop(self):
    try:
      while True:
        header = await self.reader.readexactly(8)
        size = int.from_bytes(header[0:4], 'little')
        handle = int.from_bytes(header[4:8], 'little')
        content = (await self.reader.readexactly(size)).decode('utf-8')

        if handle & 0x80000000:
          response = self.pending.pop(handle, None)
          if response is not None and not response.done():
            response.set_result(content)
          #
        else:
          self.on_callback(content)
        #
      #
    except asyncio.IncompleteReadError:
      raise ConnectionError('Connection to the server was closed') from None
    finally:
      # nobody will answer these requests anymore, wake up everyone still waiting
      for response in self.pending.values():
        if not response.done():
          response.set_exception(ConnectionError('Connection to the server was closed'))
        #
      #
      self.pending.clear()
    #
  #

  async def disconnect(self):
    if self.read_task is not None:
      self.read_task.cancel()
    #
    if self.writer is not None:
      self.writer.close()
      try:
        await self.writer.wait_closed()
      except (ConnectionError, OSError):
        pass
      #
    #
  #
#
