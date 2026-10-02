import xmlrpc.client

import log


MAX_MAPS = 5000


class Maps:
  # The server's map list, the current map and which maps were played when.
  # Map dicts are the server's SChallengeInfo: UId, Name, FileName, Author, Environment, ...

  def __init__(self, controller):
    self.controller = controller
    self.list = [] # in the server's order
    self.by_uid = {}
    self.current = None
    controller.register_event('TrackMania.BeginChallenge', self.begin_challenge)
    controller.register_event('TrackMania.ChallengeListModified', self.list_modified)
  #

  async def start(self):
    # while the server is still loading it has no map yet: BeginChallenge / ChallengeListModified will tell
    try:
      await self.refresh()
      self.current = await self.controller.call('GetCurrentChallengeInfo')
    except xmlrpc.client.Fault as fault:
      self.controller.logger.message('Map list not available yet: ' + fault.faultString, log.LOG_INFO)
    #
  #

  async def refresh(self):
    self.list = await self.controller.call('GetChallengeList', MAX_MAPS, 0)
    self.by_uid = {m['UId']: m for m in self.list}
    await self.controller.storage.maps.known(self.list)
  #

  async def list_modified(self, params):
    if params[2]: # IsListModified
      await self.refresh()
    #
  #

  async def begin_challenge(self, params):
    if not self.list:
      await self.refresh()
    #
    self.current = params[0]
    await self.controller.storage.maps.known([self.current])
    await self.controller.storage.maps.played(self.current['UId'])
    await self.controller.raise_event('MapStarted', self.current)
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
