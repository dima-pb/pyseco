import xmlrpc.client

import log


MIGRATIONS = [
  # 1
  '''
  CREATE TABLE maps (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    environment TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE TABLE plays (
    id INTEGER PRIMARY KEY,
    uid TEXT NOT NULL REFERENCES maps(uid),
    played_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX plays_uid ON plays (uid);
  ''',
]

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
    await self.controller.db.migrate('maps', MIGRATIONS)
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
    await self.controller.db.executemany(
      'INSERT OR IGNORE INTO maps (uid, name, author, environment) VALUES (?, ?, ?, ?)',
      [(m['UId'], m['Name'], m.get('Author', ''), m.get('Environment', '')) for m in self.list])
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
    uid = self.current['UId']
    await self.controller.db.execute('INSERT OR IGNORE INTO maps (uid, name, author, environment) VALUES (?, ?, ?, ?)',
      (uid, self.current['Name'], self.current.get('Author', ''), self.current.get('Environment', '')))
    await self.controller.db.execute('INSERT INTO plays (uid) VALUES (?)', (uid,))
    await self.controller.raise_event('MapStarted', self.current)
  #

  async def history(self, count):
    # the most recently started maps, newest first (the current one included): [(uid, name, played_at)]
    rows = await self.controller.db.fetchall(
      'SELECT p.uid, m.name, p.played_at FROM plays p JOIN maps m ON m.uid = p.uid ORDER BY p.id DESC LIMIT ?', (count,))
    return [(r['uid'], r['name'], r['played_at']) for r in rows]
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
