import traceback

from core import log


# Events of pyseco itself, with what the handlers get. Plugins should prefer these over the raw server
# callbacks; those can be registered too, by their name ('TrackMania.Echo', ...), and get the callback's
# parameters as tuple.
PLAYER_JOINED = 'PlayerJoined'         # services.players.Player, after the server sent the player's info
PLAYER_LEFT = 'PlayerLeft'             # services.players.Player, no longer in players.online
CHAT = 'Chat'                          # ChatMessage, chat of players that is not a /command
MAP_STARTED = 'MapStarted'             # server_api.ChallengeInfo of the new map
MAP_LIST_CHANGED = 'MapListChanged'    # None; maps.list was reloaded after maps were added or removed
SECOND_PASSED = 'SecondPassed'         # None


class ChatMessage:
  def __init__(self, player, text):
    self.player = player # services.players.Player
    self.text = text
  #
#


class Events:

  def __init__(self, logger):
    self.logger = logger
    self.handlers = {} # event name -> [async function(data)], called in the order they were registered
  #

  def register(self, name, handler):
    self.handlers.setdefault(name, []).append(handler)
  #

  async def emit(self, name, data=None):
    self.logger.message('Event ' + name + ': ' + str(data), log.LOG_DEBUG)
    for handler in self.handlers.get(name, []):
      # a failing handler (e.g. a plugin) must not take down the controller
      try:
        await handler(data)
      except Exception:
        self.logger.message('Handler ' + handler.__qualname__ + ' failed on event ' + name + ':\n'
          + traceback.format_exc(), log.LOG_ERROR)
      #
    #
  #
#
