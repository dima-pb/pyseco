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
  visits: int = 0
#


@dataclass
class Play:
  uid: str
  name: str
  played_at: str # 'YYYY-MM-DD HH:MM:SS', UTC
#


@dataclass
class Ban:
  login: str
  reason: str
  by: str # login of who banned
  until: str | None # 'YYYY-MM-DD HH:MM:SS', UTC; None: for ever
  created: str
#


@dataclass
class Record:
  login: str
  nickname: str # as last seen
  time: int # ms
  checkpoints: list # [ms] of the run, as the server sent them
  date: str # 'YYYY-MM-DD HH:MM:SS', UTC, when it was driven
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
    # remembers maps (dicts with UId, Name, Author, Environnement as the server sends them); existing ones stay
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


class PlaylistStore(ABC):

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


class ModerationStore(ABC):
  # bans and mutes

  @abstractmethod
  async def ban(self, login, reason, by, until):
    # until: 'YYYY-MM-DD HH:MM:SS' UTC or None for ever; banning again replaces the ban
    ...
  #

  @abstractmethod
  async def unban(self, login):
    # True if there was a ban (also an expired one)
    ...
  #

  @abstractmethod
  async def ban_of(self, login):
    # the Ban that is in force now, or None
    ...
  #

  @abstractmethod
  async def bans(self):
    # [Ban] in force now, newest first
    ...
  #

  @abstractmethod
  async def mute(self, login, by):
    ...
  #

  @abstractmethod
  async def unmute(self, login):
    # True if the login was muted
    ...
  #

  @abstractmethod
  async def muted(self):
    # set of muted logins
    ...
  #
#


class RecordStore(ABC):
  # the best time of every player on every map (local records)

  @abstractmethod
  async def best(self, uid, login):
    # the player's Record on the map or None
    ...
  #

  @abstractmethod
  async def save(self, uid, login, time, checkpoints):
    # the player's new best time on the map (replaces the old one), driven now
    ...
  #

  @abstractmethod
  async def ranking(self, uid, limit):
    # [Record] of the map, best first; equal times: who drove it first is first
    ...
  #
#


class KarmaStore(ABC):
  # how players rate maps: one vote (+1 or -1) per player and map

  @abstractmethod
  async def vote(self, uid, login, value):
    # the player's vote on the map; voting again replaces it
    ...
  #

  @abstractmethod
  async def unvote(self, uid, login):
    # takes the player's vote on the map back; True if there was one
    ...
  #

  @abstractmethod
  async def votes(self, uid):
    # {login: value} of the map
    ...
  #

  @abstractmethod
  async def counts(self, uids):
    # {uid: (plus, minus)} of the maps that have votes
    ...
  #
#


class Storage(ABC):
  # one backend; players, maps, playlist, moderation, records, karma are its stores

  players: PlayerStore
  maps: MapStore
  playlist: PlaylistStore
  moderation: ModerationStore
  records: RecordStore
  karma: KarmaStore

  @abstractmethod
  async def open(self):
    ...
  #

  @abstractmethod
  async def close(self):
    ...
  #
#
