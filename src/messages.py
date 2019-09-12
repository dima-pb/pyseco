import base64
from xml.sax.saxutils import escape
import xmlrpc.client


def deserialize(msg):
  return xmlrpc.client.loads(msg)
#

def serialize(params, method):
  #params_esc = [escape(p) if type(p) is str else p for p in params]
  #return xmlrpc.client.dumps(tuple(params_esc), method)
  return xmlrpc.client.dumps(params, method)
#

class Message:
  def __init__(self):
    self.method = None
    self.params = ()
  #
  
  def serialize(self, req_handle):
    xml = serialize(self.params, self.method).encode('utf-8')
    size = len(xml).to_bytes(4, 'little')
    req_bytes = req_handle.to_bytes(4, 'little')
    return b''.join([size, req_bytes, xml])
  #
  
  def parse_response(self, msg):
    object = deserialize(msg)
    return object[0][0]
  #
#


class ListMethods(Message):
  def __init__(self):
    super().__init__()
    self.method = 'system.listMethods'
  #
#

class Authenticate(Message):
  def __init__(self, username, password):
    super().__init__()
    self.method = 'Authenticate'
    self.params = (username, password)
  #
#

class EnableCallbacks(Message):
  def __init__(self, enabled = True):
    super().__init__()
    self.method = 'EnableCallbacks'
    self.params = (enabled,)
  #
#

class ChatSend(Message):
  def __init__(self, content):
    super().__init__()
    self.method = 'ChatSend'
    self.params = (content,)
  #
#

class ChatSendServerMessage(ChatSend):
  def __init__(self, content):
    super().__init__(content)
    self.method = 'ChatSendServerMessage'
  #
#

class GetCurrentChallengeInfo(Message):
  def __init__(self):
    super().__init__()
    self.method = 'GetCurrentChallengeInfo'
  #
#

class NextChallenge(Message):
  def __init__(self):
    super().__init__()
    self.method = 'NextChallenge'
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

class Echo(Message):
  def __init__(self, internal, external):
    super().__init__()
    self.method = 'Echo'
    # internal <-> external - listed wrong in the documentation
    self.params = (external, internal)
  #
#

class CallVote(Message):
  def __init__(self, command):
    super().__init__()
    self.method = 'CallVote'
    self.command_str = serialize(command.params, command.method)
    
    self.params = (self.command_str,)
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
#

class SetCallVoteTimeOut(Message):
  def __init__(self, val):
    super().__init__()
    self.method = 'SetCallVoteTimeOut'
    self.params = (val,)
  #
#

class SetCallVoteRatio(Message):
  def __init__(self, val):
    super().__init__()
    self.method = 'SetCallVoteRatio'
    self.params = (val,)
  #
#

class SetCallVoteRatios(Message):
  def __init__(self, ratios):
    super().__init__()
    self.method = 'SetCallVoteRatios'
    self.params = (ratios,)
  #
#

class CancelVote(Message):
  def __init__(self):
    super().__init__()
    self.method = 'CancelVote'
  #
#

class GetPlayerInfo(Message):
  def __init__(self, login):
    super().__init__()
    self.method = 'GetPlayerInfo'
    self.params = (login, 1)
  #
#

class GetPlayerList(Message):
  def __init__(self):
    super().__init__()
    self.method = 'GetPlayerList'
    self.params = (100, 0,)
  #
#
