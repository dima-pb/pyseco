import secrets
import time


# roles, higher includes lower
PLAYER = 0
OPERATOR = 1
ADMIN = 2
MASTERADMIN = 3
ROLE_NAMES = {PLAYER: 'player', OPERATOR: 'operator', ADMIN: 'admin', MASTERADMIN: 'masteradmin'}
ROLES_BY_NAME = {name: role for role, name in ROLE_NAMES.items()}

LINK_CODE_SECONDS = 600

MIGRATIONS = [
  # 1
  '''
  CREATE TABLE players (
    login TEXT PRIMARY KEY,
    nickname TEXT NOT NULL DEFAULT '',
    role INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT NOT NULL DEFAULT (datetime('now')),
    visits INTEGER NOT NULL DEFAULT 0
  );
  CREATE TABLE discord_links (
    discord_id INTEGER PRIMARY KEY,
    login TEXT NOT NULL REFERENCES players(login) ON DELETE CASCADE,
    linked_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  ''',
]


class Accounts:
  # Players known to the server, their roles and their linked discord accounts.
  # Masteradmins come from the settings file and can't be changed in game.

  def __init__(self, db, masteradmins):
    self.db = db
    self.masteradmins = set(masteradmins)
    self.link_codes = {} # code -> (login, expiry time), created in game, redeemed on discord
  #

  async def start(self):
    await self.db.migrate('accounts', MIGRATIONS)
  #

  async def player_seen(self, login, nickname, visit=False):
    await self.db.execute(
      'INSERT INTO players (login, nickname, visits) VALUES (?, ?, ?) '
      'ON CONFLICT (login) DO UPDATE SET nickname = excluded.nickname, last_seen = datetime(\'now\'), '
      'visits = visits + excluded.visits',
      (login, nickname or '', 1 if visit else 0))
  #

  async def role(self, login):
    if login is None:
      return PLAYER
    #
    if login in self.masteradmins:
      return MASTERADMIN
    #
    row = await self.db.fetchone('SELECT role FROM players WHERE login = ?', (login,))
    return row['role'] if row else PLAYER
  #

  async def set_role(self, login, role):
    if login in self.masteradmins:
      raise ValueError(login + ' is a masteradmin (set in the settings file)')
    #
    if role not in (PLAYER, OPERATOR, ADMIN):
      raise ValueError('only player, operator and admin can be given in game')
    #
    await self.db.execute(
      'INSERT INTO players (login, role) VALUES (?, ?) ON CONFLICT (login) DO UPDATE SET role = excluded.role',
      (login, role))
  #

  async def staff(self):
    # [(login, nickname, role)] of everybody above player, highest role first
    rows = await self.db.fetchall('SELECT login, nickname, role FROM players WHERE role > 0')
    result = [(r['login'], r['nickname'], r['role']) for r in rows if r['login'] not in self.masteradmins]
    for login in sorted(self.masteradmins):
      row = await self.db.fetchone('SELECT nickname FROM players WHERE login = ?', (login,))
      result.append((login, row['nickname'] if row else '', MASTERADMIN))
    #
    return sorted(result, key=lambda entry: (-entry[2], entry[0].lower()))
  #

  def create_link_code(self, login):
    now = time.monotonic()
    self.link_codes = {code: entry for code, entry in self.link_codes.items() if entry[1] > now}
    code = str(secrets.randbelow(900000) + 100000)
    self.link_codes[code] = (login, now + LINK_CODE_SECONDS)
    return code
  #

  async def redeem_link_code(self, code, discord_id):
    # links the discord account to the login that created the code, returns the login or None
    entry = self.link_codes.pop(code.strip(), None)
    if entry is None or entry[1] < time.monotonic():
      return None
    #
    login = entry[0]
    await self.db.execute('INSERT OR IGNORE INTO players (login) VALUES (?)', (login,))
    await self.db.execute(
      'INSERT INTO discord_links (discord_id, login) VALUES (?, ?) '
      'ON CONFLICT (discord_id) DO UPDATE SET login = excluded.login, linked_at = datetime(\'now\')',
      (discord_id, login))
    return login
  #

  async def login_for_discord(self, discord_id):
    row = await self.db.fetchone('SELECT login FROM discord_links WHERE discord_id = ?', (discord_id,))
    return row['login'] if row else None
  #

  async def unlink_discord(self, discord_id):
    cursor = await self.db.execute('DELETE FROM discord_links WHERE discord_id = ?', (discord_id,))
    return cursor.rowcount > 0
  #
#
