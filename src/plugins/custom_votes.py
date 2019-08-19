import time

from plugins.plugin import Plugin
import messages

class CustomVote(Plugin):

  REPLAY = 'replay'
  SKIP = 'skip'

  def __init__(self, controller):
    super().__init__(controller)
    self.controller.register_event('TrackMania.PlayerChat', self.check_command)
    self.controller.register_event('TrackMania.Echo', self.echo)
  #

  def check_command(self, params):
    if params[0] == 0: # don't react to server-own messages
      return
    #
    msg = params[2].strip()
    if not msg.startswith('/'):
      return
    #
    msg = msg[1:]
    
    cmd = None
    if msg == self.REPLAY:
      cmd = messages.Echo(self.REPLAY, 'Replay this map')
    elif msg == self.SKIP:
      cmd = messages.Echo(self.SKIP, 'Skip this map')
    #
    
    if cmd is not None:
      self.controller.call_vote(cmd)
    #
  #
  
  def echo(self, params):
    if params[0] == self.REPLAY:
      self.controller.chat_send_server_message('Replay vote passed')
      map = self.controller.get_current_challenge_info()
      filename = map['FileName']
      self.controller.choose_next_challenge(filename)
    elif params[0] == self.SKIP:
      self.controller.chat_send_server_message('Skip vote passed')
      self.controller.next_challenge()
    #
  #
#

