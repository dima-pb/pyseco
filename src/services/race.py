from core import events


class Checkpoint:
  def __init__(self, player, time, index, lap):
    self.player = player # services.players.Player
    self.time = time # ms since the start of the run
    self.index = index # 0 for the first checkpoint of the run
    self.lap = lap
  #
#


class Finish:
  def __init__(self, player, time, checkpoints, map):
    self.player = player # services.players.Player
    self.time = time # ms
    self.checkpoints = checkpoints # [ms] of this run, as the server sent them
    self.map = map # server_api.ChallengeInfo
  #
#


class Race:
  # What happens on the track: collects the checkpoints of every player's run and raises events.CHECKPOINT
  # and events.PLAYER_FINISHED (with the checkpoints of the run). A run starts with its first checkpoint;
  # the server's finish with time 0 (a player restarted or gave up) drops the run.

  def __init__(self, controller):
    self.controller = controller
    self.runs = {} # login -> [checkpoint times] of the current run
    controller.events.register('TrackMania.PlayerCheckpoint', self.checkpoint)
    controller.events.register('TrackMania.PlayerFinish', self.finish)
    controller.events.register(events.MAP_STARTED, self.map_started)
    controller.events.register(events.PLAYER_LEFT, self.player_left)
  #

  async def checkpoint(self, params):
    # params: player uid, login, time, current lap, checkpoint index
    login, time, lap, index = params[1], params[2], params[3], params[4]
    if index == 0:
      self.runs[login] = []
    #
    self.runs.setdefault(login, []).append(time)
    player = await self.controller.players.get(login)
    if player is not None:
      await self.controller.events.emit(events.CHECKPOINT, Checkpoint(player, time, index, lap))
    #
  #

  async def finish(self, params):
    # params: player uid, login, time (0: the player restarted or gave up)
    login, time = params[1], params[2]
    checkpoints = self.runs.pop(login, [])
    if time <= 0 or self.controller.maps.current is None:
      return
    #
    player = await self.controller.players.get(login)
    if player is not None:
      await self.controller.events.emit(events.PLAYER_FINISHED,
        Finish(player, time, checkpoints, self.controller.maps.current))
    #
  #

  async def map_started(self, map):
    self.runs = {}
  #

  async def player_left(self, player):
    self.runs.pop(player.login, None)
  #
#
