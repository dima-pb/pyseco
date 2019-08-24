import select
import socket

import messages
import xmlrpc.client


class TMClient:

  def __init__(self, url, port):
    self.supported_protocols = ['GBXRemote 2']
    self.url = url
    self.port = port
    self.soc = None
    self.callbacks = []
    self.req_handle = 0x80000000
  #

  def connect(self):
    self.soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.soc.connect((self.url, self.port))
    
    size = int.from_bytes(self.soc.recv(4), 'little')
    protocol = self.soc.recv(size).decode('utf-8')
    if protocol not in self.supported_protocols:
      raise ValueError('Unsupported protocol ' + protocol)
    #
    
    cb_enable = messages.EnableCallbacks()
    if not self.send(cb_enable):
      raise Exception('Unable to enable callbacks')
    #
  #
  
  def send(self, msg):
    try:
      content = msg.serialize(self.req_handle)
      self.soc.send(content)
      
      req_handle = None
      while req_handle != self.req_handle:
        req_handle, response = self.receive()
        if req_handle != self.req_handle:
          # it's not the response to our message -> must be a callback -> let the main loop deal with it
          self.callbacks.append(response)
        #
      #
      self.req_handle += 1
      response_obj = msg.parse_response(response)
    except Exception as exc:
      return exc
    #
    return response_obj
  #
  
  def receive(self):
    header = self.soc.recv(8)
    size = int.from_bytes(header[0:4], 'little')
    req_handle = int.from_bytes(header[4:8], 'little')
    
    content = self.soc.recv(size)
    return req_handle, content.decode('utf-8')
  #
  
  def load_callbacks(self):
    ready = True
    while ready:
      ready = select.select([self.soc], [], [], 0.02)[0]
      if ready:
        callback = self.receive()[1]
        self.callbacks.append(callback)
      #
    #
    return self.callbacks
  #
  
  def reset_callbacks(self):
    self.callbacks = []
  #
  
  def disconnect(self):
    self.soc.shutdown(socket.SHUT_RDWR)
    self.soc.close()
  #
#
