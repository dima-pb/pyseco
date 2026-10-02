from abc import ABC, abstractmethod
from dataclasses import dataclass


# The data pyseco keeps, independent of where it is kept. The controller and the plugins only use
# these interfaces; a backend (storage/sqlite.py, storage/memory.py, ...) implements all of them.
# Methods take and return plain values or the dataclasses below, never backend objects (rows, cursors).
# All methods are async, a backend may do I/O.


@dataclass
class StoredPlayer:
  login: str
  nickname: str
  role: int
#


@dataclass
class Play:
  uid: str
  name: str
  played_at: str # 'YYYY-MM-DD HH:MM:SS', UTC
#


@dataclass
class QueuedMap:
  uid: str
  filename: str
  name: str
  environment: str
  login: str
  nickname: str
  source: str
#


class PlayerStore(ABC):

  @abstractmethod
  async def seen(self, login, nickname, visit):
    # creates the player if new, updates the nickname and last seen time; visit counts a new visit
    ...
  #

  @abstractmethod
  async def role(self, login):
    # the stored role, 0 (player) for unknown logins
    ...
  #

  @abstractmethod
  async def set_role(self, login, role):
    # creates the player if new
    ...
  #

  @abstractmethod
  async def get(self, login):
    # StoredPlayer or None
    ...
  #

  @abstractmethod
  async def with_role(self):
    # [StoredPlayer] of everybody with a role above player
    ...
  #

  @abstractmethod
  async def link_discord(self, discord_id, login):
    # creates the player if new; a discord account links to one login, linking again replaces it
    ...
  #

  @abstractmethod
  async def login_for_discord(self, discord_id):
    # the linked login or None
    ...
  #

  @abstractmethod
  async def unlink_discord(self, discord_id):
    # True if there was a link
    ...
  #
#


class MapStore(ABC):

  @abstractmethod
  async def known(self, maps):
    # remembers maps (dicts with UId, Name, Author, Environment as the server sends them); existing ones stay
    ...
  #

  @abstractmethod
  async def played(self, uid):
    # a map started now
    ...
  #

  @abstractmethod
  async def history(self, count):
    # [Play] of the last started maps, newest first
    ...
  #
#


class JukeboxStore(ABC):

  @abstractmethod
  async def queue(self):
    # [QueuedMap] in order
    ...
  #

  @abstractmethod
  async def set_queue(self, entries):
    # replaces the queue with [QueuedMap]
    ...
  #

  @abstractmethod
  async def temporary_maps(self):
    # {uid: filename} of maps to remove from the server after they were played
    ...
  #

  @abstractmethod
  async def add_temporary(self, uid, filename):
    ...
  #

  @abstractmethod
  async def remove_temporary(self, uid):
    ...
  #
#


class Storage(ABC):
  # one backend; players, maps, jukebox are its stores

  players: PlayerStore
  maps: MapStore
  jukebox: JukeboxStore

  @abstractmethod
  async def open(self):
    ...
  #

  @abstractmethod
  async def close(self):
    ...
  #
#
