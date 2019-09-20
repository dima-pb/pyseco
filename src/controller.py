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
    
    self.register_event('TrackMania.PlayerConnect', self.player_connect)
    self.register_event('TrackMania.PlayerDisconnect', self.player_disconnect)
    self.register_event('TrackMania.PlayerInfoChanged', self.player_info_changed)
  #

  def run(self):
    self.client.connect()
    self.authenticate(self.username, self.password)
    players = self.get_player_list()
    if players is not None:
      for player in players:
        self.add_player_info(player['Login'], player)
      #
    #
    
    self.plugins = Plugins(self)
    
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
      self.logger.message('Unlisted player requested ' + login, log.LOG_WARNING)
      info = self.get_playerinfo(login)
      self.add_player_info(login, info)
    #
    player = self.players[login]
    if player.nickname is None:
      info = self.get_playerinfo(login)
      self.add_player_info(login, info)
    #
    
    return player
  #
  
  def add_player_info(self, login, info):
    if login not in self.players:
      p = player.Player(login)
    else:
      p = self.players[login]
    #
    just_entered = p.id == None
    initialized = False
    
    if info is not None:
      p.nickname = info['NickName']
      p.id = info['PlayerId']
      initialized = p.id != None
      p.team_id = info['TeamId']
      if 'SpectatorStatus' in info:
        p.is_spec = info['SpectatorStatus'] != 0
      elif 'IsSpectator' in info:
        p.is_spec = info['IsSpectator']
      #
      p.ladder_rank = info['LadderRanking']
      if 'Flags' in info:
        p.flags = info['Flags']
      #
    #
    self.players[login] = p
    
    if just_entered and initialized:
      self.raise_event('PlayerConnectComplete', login)
    #
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
    self.add_player_info(login, dict)
  #
  
  def request(self, message):
    try:
      return self.client.send(message)
    except Exception as exc:
      self.logger.message(message.method + ' returned with an error ' + str(exc), log.LOG_ERROR)
      return None
    #
  #
  
  
  def authenticate(self, username, password):
    login = messages.Authenticate(username, password)
    return self.request(login)
  #
  
  def list_methods(self):
    methods = messages.ListMethods()
    return self.request(methods)
  #
  
  def chat_send(self, content):
    chat = messages.ChatSend(content)
    return self.request(chat)
  #
  
  def get_current_challenge_info(self):
    info = messages.GetCurrentChallengeInfo()
    return self.request(info)
  #
  
  def choose_next_challenge(self, filename):
    map = messages.ChooseNextChallenge(filename)
    return self.request(map)
  #
  
  def next_challenge(self):
    next = messages.NextChallenge()
    return self.request(next)
  #
  
  def chat_send_server_message(self, content):
    chat = messages.ChatSendServerMessage(content)
    return self.request(chat)
  #
  
  def call_vote(self, cmd):
    vote = messages.CallVote(cmd)
    return self.request(vote)
  #
  
  def call_vote_ex(self, cmd, ratio, timeout, voter):
    vote = messages.CallVoteEx(cmd, ratio, timeout, voter)
    return self.request(vote)
  #
  
  def current_vote_info(self):
    info = messages.GetCurrentCallVote()
    return self.request(info)
  #
  
  def set_callvote_timeout(self, val):
    timeout = messages.SetCallVoteTimeOut(val)
    return self.request(timeout)
  #
  
  def set_callvote_ratio(self, val):
    ratio = messages.SetCallVoteRatio(val)
    return self.request(ratio)
  #
  
  def set_callvote_ratios(self, tuple):
    ratios = messages.SetCallVoteRatios(tuple)
    return self.request(ratios)
  #
  
  def cancel_vote(self):
    cancel = messages.CancelVote()
    return self.request(cancel)
  #
  
  def get_playerinfo(self, login):
    info = messages.GetPlayerInfo(login)
    return self.request(info)
  #
  
  def get_player_list(self):
    list = messages.GetPlayerList()
    return self.request(list)
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

