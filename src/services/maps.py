import xmlrpc.client

from core import events, log


MAX_MAPS = 5000


class Maps:
  # The server's map list, the current map and which maps were played when.
  # Maps are the server's dicts, see core.server_api.ChallengeInfo.

  def __init__(self, controller):
    self.controller = controller
    self.list = [] # in the server's order
    self.by_uid = {}
    self.current = None
    controller.events.register('TrackMania.BeginChallenge', self.begin_challenge)
    controller.events.register('TrackMania.ChallengeListModified', self.list_modified)
    controller.events.register('TrackMania.EndChallenge', self.end_challenge)
  #

  async def start(self):
    # while the server is still loading it has no map yet: BeginChallenge / ChallengeListModified will tell
    try:
      await self.refresh()
      self.current = await self.controller.server.get_current_challenge_info()
    except xmlrpc.client.Fault as fault:
      self.controller.logger.message('Map list not available yet: ' + fault.faultString, log.LOG_INFO)
    #
  #

  async def refresh(self):
    self.list = await self.controller.server.get_challenge_list(MAX_MAPS, 0)
    self.by_uid = {m['UId']: m for m in self.list}
    await self.controller.storage.maps.known(self.list)
  #

  async def list_modified(self, params):
    if params[2]: # IsListModified
      await self.refresh()
      await self.controller.events.emit(events.MAP_LIST_CHANGED)
    #
  #

  async def begin_challenge(self, params):
    if not self.list:
      await self.refresh()
    #
    self.current = params[0]
    await self.controller.storage.maps.known([self.current])
    await self.controller.storage.maps.played(self.current['UId'])
    await self.controller.events.emit(events.MAP_STARTED, self.current)
  #

  async def end_challenge(self, params):
    # params: rankings, map, was warm-up, match continues, restart
    await self.controller.events.emit(events.MAP_ENDED, params[1])
  #

  async def history(self, count):
    # the most recently started maps, newest first (the current one included): [(uid, name, played_at)]
    return [(p.uid, p.name, p.played_at) for p in await self.controller.storage.maps.history(count)]
  #

  async def recent_uids(self, count):
    # uids of the last maps played, without the current one
    return [uid for uid, _, _ in (await self.history(count + 1))[1:]]
  #

  def index_of(self, uid):
    for i, m in enumerate(self.list):
      if m['UId'] == uid:
        return i
      #
    #
    return None
  #
#
