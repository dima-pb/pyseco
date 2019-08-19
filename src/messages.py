import base64
import xmlrpc.client


def deserialize(msg):
  try:
    return xmlrpc.client.loads(msg)
  except Exception as exc:
    return exc
  #
#

def serialize(params, method):
  return xmlrpc.client.dumps(params, method)
#

class Message:
  def __init__(self):
    self.method = None
    self.params = ()
  #
  
  def serialize(self, req_handle):
    xml = serialize(self.params, self.method)
    size = len(xml).to_bytes(4, 'little')
    req_bytes = req_handle.to_bytes(4, 'little')
    return b''.join([size, req_bytes, xml.encode('utf-8')])
  #
  
  def parse_response(self, msg):
    raise Exception('Method parse_response not implemented.')
  #
  
  def parse_response_bool(self, msg):
    object = deserialize(msg)
    if type(object) is not tuple or len(object) == 0:
      raise Exception('Invalid response')
    #
    if type(object[0]) is not tuple or len(object[0]) == 0:
      raise Exception('Invalid response')
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

class GetCurrentChallengeInfo(Message):
  def __init__(self):
    super().__init__()
    self.method = 'GetCurrentChallengeInfo'
  #
  
  def parse_response(self, response):
    object = deserialize(response)
    if type(object) is not tuple or len(object) == 0 or type(object[0]) is not tuple or type(object[0][0]) is not dict:
      raise Exception('Invalid response to GetCurrentChallengeInfo request')
    #
    
    return object[0][0]
  #
#

class NextChallenge(Message):
  def __init__(self):
    super().__init__()
    self.method = 'NextChallenge'
  #
  
  def parse_response(self, response):
    return self.parse_response_bool(response)
  #
#

class ChooseNextChallenge(Message):
  def __init__(self, filename):
    super().__init__()
    self.method = 'ChooseNextChallenge'
    self.params = (filename,)
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

class Echo(Message):
  def __init__(self, internal, external):
    super().__init__()
    self.method = 'Echo'
    # internal <-> external - listed wrong in the documentation
    self.params = (external, internal)
  #
  
  def parse_response(self, response):
    return self.parse_response_bool(response)
  #
#

class CallVote(Message):
  def __init__(self, command):
    super().__init__()
    self.method = 'CallVote'
    self.command_str = serialize(command.params, command.method)
    
    self.params = (self.command_str,)
  #

  def parse_response(self, response):
    return deserialize(response)
  #
#

class CallVoteEx(CallVote):
  def __init__(self, command, ratio, timeout, voter):
    super().__init__(command)
    self.method = 'CallVoteEx'
    self.params = (self.command_str, ratio, timeout, voter)
  #
#

class GetCurrentCallVote(Message):
  def __init__(self):
    super().__init__()
    self.method = 'GetCurrentCallVote'
  #
  
  def parse_response(self, response):
    return deserialize(response)
  #
#

