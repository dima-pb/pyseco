import traceback

from core import log, roles


GAME = 'game'
DISCORD = 'discord'


class UsageError(Exception):
  # raise from a command handler to tell the user how to use the command
  pass
#


class Context:
  # Who runs a command and how to answer. The same command handler serves the game chat
  # (/name args) and discord (!name args).

  def __init__(self, source, login, display_name, role, args, reply, discord_id=None):
    self.source = source
    self.login = login # TM login; on discord the linked login or None
    self.display_name = display_name
    self.role = role
    self.args = args # list of words after the command name
    self.discord_id = discord_id
    self._reply = reply
  #

  async def reply(self, text):
    await self._reply(text)
  #
#


class Command:
  def __init__(self, name, handler, role, help, usage, sources):
    self.name = name
    self.handler = handler
    self.role = role
    self.help = help
    self.usage = usage
    self.sources = sources
  #
#


class Commands:

  def __init__(self, logger):
    self.logger = logger
    # source -> name or alias -> Command; the same name may mean different commands in game and on discord
    self.commands = {GAME: {}, DISCORD: {}}
  #

  def register(self, name, handler, role=roles.PLAYER, help='', usage='', sources=(GAME, DISCORD), aliases=()):
    command = Command(name, handler, role, help, usage, tuple(sources))
    for source in command.sources:
      for key in (name,) + tuple(aliases):
        if key in self.commands[source]:
          raise ValueError('Command ' + key + ' is already registered for ' + source)
        #
        self.commands[source][key] = command
      #
    #
  #

  def available(self, role, source):
    # commands the role may use from this source, without aliases, sorted by name
    unique = {c.name: c for c in self.commands[source].values()}
    return [c for name, c in sorted(unique.items()) if role >= c.role]
  #

  async def run(self, ctx, name):
    # returns False if there is no such command for this source (so others may handle it)
    command = self.commands[ctx.source].get(name.lower())
    if command is None:
      return False
    #
    if ctx.role < command.role:
      await ctx.reply('You need to be ' + roles.NAMES[command.role] + ' to use this command.')
      return True
    #
    try:
      await command.handler(ctx)
    except UsageError as exc:
      prefix = '/' if ctx.source == GAME else '!'
      await ctx.reply((str(exc) + ' ' if str(exc) else '') + 'Usage: ' + prefix + command.name
        + (' ' + command.usage if command.usage else ''))
    except Exception:
      self.logger.message('Command ' + command.name + ' failed:\n' + traceback.format_exc(), log.LOG_ERROR)
      await ctx.reply('The command failed, see the pyseco log.')
    #
    return True
  #
#
