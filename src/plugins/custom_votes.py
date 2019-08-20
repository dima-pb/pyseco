import time
import os

from plugins.plugin import Plugin
import messages

class CustomVote(Plugin):

  REPLAY = 'replay'
  SKIP = 'skip'

  def __init__(self, controller):
    super().__init__(controller)
    
    self.read_settings()
    self.controller.set_callvote_timeout(self.timeout)
    self.controller.set_callvote_ratios((
      { 'Command': 'ChallengeRestart', 'Ratio': -1.0 },
      { 'Command': 'NextChallenge', 'Ratio': -1.0 },
    ))
    
    self.controller.register_event('TrackMania.PlayerChat', self.check_command)
    self.controller.register_event('TrackMania.Echo', self.echo)
  #
  
  def read_settings(self):
    cfg = open(os.path.join('plugins', 'custom_votes.ini'), 'r')
    self.timeout = 30000
    self.ratio = 0.5
    for line in cfg:
      kv = line.split('=')
      if len(kv) != 2:
        continue
      #
      if kv[0] == 'timeout':
        self.timeout = int(kv[1].strip())
      if kv[0] == 'ratio':
        self.ratio = float(kv[1].strip())
      #
    #
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
      print(self.controller.call_vote_ex(cmd, self.ratio, self.timeout, 1))
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

