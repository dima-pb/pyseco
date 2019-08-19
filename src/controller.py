import time
import traceback

import client
import config
import log
import messages
import player
from plugins.plugins import Plugins


class TMController:

  def __init__(self, config, logger):
    self.logger = logger
    self.client = client.TMClient(config.URL, config.PORT)
    self.username = config.USERNAME_SUPERADMIN
    self.password = config.PASSWORD_SUPERADMIN
    self.players = {} # login-string -> player object
    self.events = {} # string -> list of receiver-callbacks
    self.plugins = Plugins(self)
    
    self.register_event('TrackMania.PlayerConnect', self.player_connect)
    self.register_event('TrackMania.PlayerDisconnect', self.player_disconnect)
    self.register_event('TrackMania.PlayerInfoChanged', self.player_info_changed)
  #

  def run(self):
    self.client.connect()
    self.authenticate(self.username, self.password)
    
    delay = 0.25
    prev_tick = time.time()
    prev_second = prev_tick
    while True:
      cbs = self.client.load_callbacks()
      
      for cb in cbs:
        object = messages.deserialize(cb)
        self.process_callback(object)
      #
      
      self.client.reset_callbacks()
      
      self.raise_event('tick', None)
      
      now = time.time()
      if now - prev_second >= 1.0:
        self.raise_event('second_passed', None)
        prev_second = now
      #
      
      now = time.time()
      duration = now - prev_tick
      if duration < delay:
        time.sleep(delay - duration)
      #
      prev_tick = now
    #
  #
  
  def process_callback(self, cb):
    self.logger.message('Processing callback ' + str(cb), log.LOG_VERBOSE)
    if type(cb) is not tuple or len(cb) != 2:
      self.logger.message('Unexpected callback value ' + str(cb), log.LOG_WARNING)
      return
    #
    
    event_name = cb[1]
    params = cb[0]
    self.raise_event(event_name, params)
    #
  #
  
  def register_event(self, event_name, method):
    if event_name not in self.events:
      self.events[event_name] = []
    #
    self.events[event_name].append(method)
  #
  
  def raise_event(self, event_name, params):
    self.logger.message('Raising event ' + event_name + ' with parameters ' + str(params), log.LOG_DEBUG)
    if event_name not in self.events:
      return
    #
    for method in self.events[event_name]:
      method(params)
    #
  #
  
  def get_player_by_login(self, login):
    if login not in self.players:
      self.logger.message('Unlisted player requested' + login, log.LOG_WARNING)
      p = player.Player(login)
      self.players[login] = p
    #
    return self.players[login]
  #
  
  def player_connect(self, params):
    login = params[0]
    is_spec = params[1]
    
    p = player.Player(login, is_spec)
    self.players[login] = p
  #
  
  def player_disconnect(self, params):
    p = self.get_player_by_login(params[0])
    del self.players[params[0]]
  #
  
  def player_info_changed(self, params):
    dict = params[0]
    
    login = dict['Login']
    p = self.get_player_by_login(login)
    
    p.nickname = dict['NickName']
    p.id = dict['PlayerId']
    p.team_id = dict['TeamId']
    p.is_spec = dict['SpectatorStatus']
    p.ladder_rank = dict['LadderRanking']
    p.flags = dict['Flags']
  #
  
  
  def authenticate(self, username, password):
    login = messages.Authenticate(username, password)
    return self.client.send(login)
  #
  
  def list_methods(self):
    methods = messages.ListMethods()
    return self.client.send(methods)
  #
  
  def chat_send(self, content):
    chat = messages.ChatSend(content)
    return self.client.send(chat)
  #
  
  def get_current_challenge_info(self):
    info = messages.GetCurrentChallengeInfo()
    return self.client.send(info)
  #
  
  def choose_next_challenge(self, filename):
    map = messages.ChooseNextChallenge(filename)
    return self.client.send(map)
  #
  
  def next_challenge(self):
    next = messages.NextChallenge()
    return self.client.send(next)
  #
  
  def chat_send_server_message(self, content):
    chat = messages.ChatSendServerMessage(content)
    return self.client.send(chat)
  #
  
  def call_vote(self, cmd):
    vote = messages.CallVote(cmd)
    return self.client.send(vote)
  #
  
  def current_vote_info(self):
    info = messages.GetCurrentCallVote()
    return self.client.send(info)
  #
#


cfg = config.TM_CONFIG()
logger = log.Logging(cfg.LOG_PATH, cfg.LOG_LEVEL)

controller = TMController(cfg, logger)
try:
  controller.run()
except Exception as exc:
  tb = traceback.format_exc()
  logger.message(str(exc), log.LOG_ERROR)
  logger.message(tb, log.LOG_ERROR)
  controller.client.disconnect()
#

