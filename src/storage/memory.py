import copy
import datetime

from storage.interfaces import (Ban, JukeboxStore, MapStore, ModerationStore, Play, PlayerStore, QueuedMap, Storage,
  StoredPlayer)


# Keeps everything in memory, lost when pyseco stops. Useful for tests and as a template for new backends.


def now():
  return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
#


class MemoryPlayerStore(PlayerStore):

  def __init__(self):
    self.players = {} # login -> StoredPlayer
    self.links = {} # discord id -> login
  #

  def _player(self, login):
    if login not in self.players:
      self.players[login] = StoredPlayer(login, '', 0)
    #
    return self.players[login]
  #

  async def seen(self, login, nickname, visit):
    player = self._player(login)
    player.nickname = nickname or ''
    player.visits += 1 if visit else 0
  #

  async def role(self, login):
    player = self.players.get(login)
    return player.role if player else 0
  #

  async def set_role(self, login, role):
    self._player(login).role = role
  #

  async def get(self, login):
    player = self.players.get(login)
    return copy.copy(player) if player else None
  #

  async def with_role(self):
    return [copy.copy(p) for p in self.players.values() if p.role > 0]
  #

  async def link_discord(self, discord_id, login):
    self._player(login)
    self.links[discord_id] = login
  #

  async def login_for_discord(self, discord_id):
    return self.links.get(discord_id)
  #

  async def unlink_discord(self, discord_id):
    return self.links.pop(discord_id, None) is not None
  #
#


class MemoryMapStore(MapStore):

  def __init__(self):
    self.names = {} # uid -> name
    self.plays = [] # [Play], oldest first
  #

  async def known(self, maps):
    for m in maps:
      self.names.setdefault(m['UId'], m['Name'])
    #
  #

  async def played(self, uid):
    self.plays.append(Play(uid, self.names.get(uid, ''), now()))
  #

  async def history(self, count):
    return [copy.copy(p) for p in reversed(self.plays[-count:])] if count > 0 else []
  #
#


class MemoryJukeboxStore(JukeboxStore):

  def __init__(self):
    self._queue = []
    self._temporary = {}
  #

  async def queue(self):
    return [copy.copy(e) for e in self._queue]
  #

  async def set_queue(self, entries):
    self._queue = [QueuedMap(e.uid, e.filename, e.name, e.environment, e.login, e.nickname, e.source) for e in entries]
  #

  async def temporary_maps(self):
    return dict(self._temporary)
  #

  async def add_temporary(self, uid, filename):
    self._temporary[uid] = filename
  #

  async def remove_temporary(self, uid):
    self._temporary.pop(uid, None)
  #
#


class MemoryModerationStore(ModerationStore):

  def __init__(self):
    self._bans = {} # login -> Ban
    self._muted = set()
  #

  async def ban(self, login, reason, by, until):
    self._bans[login] = Ban(login, reason, by, until, now())
  #

  async def unban(self, login):
    return self._bans.pop(login, None) is not None
  #

  async def ban_of(self, login):
    ban = self._bans.get(login)
    return copy.copy(ban) if ban and (ban.until is None or ban.until > now()) else None
  #

  async def bans(self):
    active = [copy.copy(b) for b in self._bans.values() if b.until is None or b.until > now()]
    return sorted(sorted(active, key=lambda b: b.login), key=lambda b: b.created, reverse=True)
  #

  async def mute(self, login, by):
    self._muted.add(login)
  #

  async def unmute(self, login):
    if login not in self._muted:
      return False
    #
    self._muted.discard(login)
    return True
  #

  async def muted(self):
    return set(self._muted)
  #
#


class MemoryStorage(Storage):

  def __init__(self):
    self.players = MemoryPlayerStore()
    self.maps = MemoryMapStore()
    self.jukebox = MemoryJukeboxStore()
    self.moderation = MemoryModerationStore()
  #

  async def open(self):
    pass
  #

  async def close(self):
    pass
  #
#
