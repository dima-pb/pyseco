import time
import os

import log
from plugins.plugin import Plugin
import messages
import utilities


class CustomVote(Plugin):

  def __init__(self, controller):
    super().__init__(controller)
    
    self.read_settings()
    self.controller.set_callvote_timeout(self.timeout)
    self.controller.set_callvote_ratios((
      { 'Command': 'ChallengeRestart', 'Ratio': -1.0 },
      { 'Command': 'NextChallenge', 'Ratio': -1.0 },
    ))
    
    self.callvotes = {
      'replay': ['replay', 'Replay this map', self.replay_map],
      'restart': ['replay', 'Replay this map', self.replay_map],
      'res': ['replay', 'Replay this map', self.replay_map],
      'skip': ['skip', 'Skip this map', self.skip_map],
      'next': ['skip', 'Skip this map', self.skip_map],
    }
    
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
    
    echo = None
    if msg in self.callvotes:
      vote_details = self.callvotes[msg]
      echo = messages.Echo(vote_details[0], vote_details[1])
      
      login = params[1]
      player = self.controller.get_player_by_login(login)
      try:
        if self.controller.call_vote_ex(echo, self.ratio, self.timeout, 1):
          nickname_clean = utilities.strip_colors(player.nickname)
          #self.controller.chat_send_server_message(nickname_clean + ' started the vote: ' + vote_details[1] + '')
          #self.controller.chat_send_server_message(nickname_clean)
        #
      except Exception as exc:
        self.controller.logger.message(str(exc), log.LOG_ERROR)
      #
    #
  #
  
  def echo(self, params):
    cmd_str = params[0]
    msg = params[1]
    if cmd_str not in self.callvotes:
      return
    #
    
    vote_info = self.callvotes[cmd_str]
    self.controller.chat_send_server_message('Vote: "' + msg + '" passed')
    
    action = vote_info[2]
    action()
  #
  
  def replay_map(self):
    map = self.controller.get_current_challenge_info()
    filename = map['FileName']
    self.controller.choose_next_challenge(filename)
  #
  
  def skip_map(self):
    self.controller.next_challenge()
  #
#

