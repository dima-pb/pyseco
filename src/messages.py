import base64
import xmlrpc.client


def deserialize(msg):
  return xmlrpc.client.loads(msg)
#

class Message:
  def __init__(self):
    self.method = None
    self.params = ()
  #
  
  def serialize(self, req_handle):
    xml = xmlrpc.client.dumps(self.params, self.method).encode('utf-8')
    size = len(xml).to_bytes(4, 'little')
    
    req_bytes = req_handle.to_bytes(4, 'little')
    
    content = b''.join([size, req_bytes, xml])
    return content
  #
  
  def parse_response(self, msg):
    raise Exception('Method parse_response not implemented.')
  #
  
  def parse_response_bool(self, msg):
    object = deserialize(msg)
    if type(object) is not tuple or len(object) == 0:
      raise Exception('Invalid response to login-request')
    #
    if type(object[0]) is not tuple or len(object[0]) == 0:
      raise Exception('Invalid response to login-request')
    #
    return object[0][0]
  #
#


class ListMethods(Message):
  def __init__(self):
    super().__init__()
    self.method = 'system.listMethods'
  #
  
  def parse_response(self, response):
    object = deserialize(response)
    
    if type(object) is not tuple or len(object) == 0 or type(object[0]) is not tuple:
      raise Exception('Invalid response to system.listMethods request')
    #
    
    return object[0][0]
  #
#

class Authenticate(Message):
  def __init__(self, username, password):
    super().__init__()
    self.method = 'Authenticate'
    self.params = (username, password)
  #
  
  def parse_response(self, response):
    return self.parse_response_bool(response)
  #
#

class EnableCallbacks(Message):
  def __init__(self, enabled = True):
    super().__init__()
    self.method = 'EnableCallbacks'
    self.params = (enabled,)
  #
  
  def parse_response(self, response):
    return self.parse_response_bool(response)
  #
#

class ChatSend(Message):
  def __init__(self, content):
    super().__init__()
    self.method = 'ChatSend'
    self.params = (content,)
  #
  
  def parse_response(self, response):
    return self.parse_response_bool(response)
  #
#

class ChatSendServerMessage(ChatSend):
  def __init__(self, content):
    super().__init__(content)
    self.method = 'ChatSendServerMessage'
  #
#

