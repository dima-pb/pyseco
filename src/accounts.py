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


class Accounts:
  # Players known to the server, their roles and their linked discord accounts.
  # Masteradmins come from the settings file and can't be changed in game.

  def __init__(self, store, masteradmins):
    self.store = store # storage.interfaces.PlayerStore
    self.masteradmins = set(masteradmins)
    self.link_codes = {} # code -> (login, expiry time), created in game, redeemed on discord
  #
  
  async def player_seen(self, login, nickname, visit=False):
    await self.store.seen(login, nickname, visit)
  #
  
  async def role(self, login):
    if login is None:
      return PLAYER
    #
    if login in self.masteradmins:
      return MASTERADMIN
    #
    return await self.store.role(login)
  #
  
  async def set_role(self, login, role):
    if login in self.masteradmins:
      raise ValueError(login + ' is a masteradmin (set in the settings file)')
    #
    if role not in (PLAYER, OPERATOR, ADMIN):
      raise ValueError('only player, operator and admin can be given in game')
    #
    await self.store.set_role(login, role)
  #
  
  async def staff(self):
    # [(login, nickname, role)] of everybody above player, highest role first
    result = [(p.login, p.nickname, p.role) for p in await self.store.with_role() if p.login not in self.masteradmins]
    for login in sorted(self.masteradmins):
      player = await self.store.get(login)
      result.append((login, player.nickname if player else '', MASTERADMIN))
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
    await self.store.link_discord(discord_id, entry[0])
    return entry[0]
  #
  
  async def login_for_discord(self, discord_id):
    return await self.store.login_for_discord(discord_id)
  #
  
  async def unlink_discord(self, discord_id):
    return await self.store.unlink_discord(discord_id)
  #
#
