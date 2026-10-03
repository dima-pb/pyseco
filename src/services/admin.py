from core import commands, roles
from services.windows import ListWindow


class Action:
  def __init__(self, name, handler, role, help, usage):
    self.name = name
    self.handler = handler
    self.role = role
    self.help = help
    self.usage = usage
  #
#


class Admin:
  # /admin <action> [args]: what admins (and operators) do directly, while the plain commands like /skip and
  # /replay stay votes. Services and plugins add their actions:
  #   controller.admin.register('next', handler, role=roles.OPERATOR, help='...', usage='')
  # The handler gets the commands.Context of /admin with ctx.args after the action's name.

  def __init__(self, controller):
    self.controller = controller
    self.actions = {} # name -> Action
    self.window = ListWindow(controller.ui, width=90, columns=[30, 56])
    controller.commands.register('admin', self.cmd_admin, role=roles.OPERATOR, help='admin actions, /admin lists them',
      usage='<action> [...]')
  #

  def register(self, name, handler, role=roles.ADMIN, help='', usage=''):
    if name in self.actions:
      raise ValueError('Admin action ' + name + ' is already registered')
    #
    self.actions[name] = Action(name, handler, max(role, roles.OPERATOR), help, usage)
  #

  def available(self, role):
    return [a for name, a in sorted(self.actions.items()) if role >= a.role]
  #

  @staticmethod
  def who(ctx):
    # the name to tell everybody who did it
    if ctx.source == commands.DISCORD:
      return '$fff' + ctx.display_name.replace('$', '$$') + '$z$s (discord)'
    #
    return '$fff' + ctx.display_name + '$z$s'
  #

  async def run(self, ctx, name):
    # runs the action for ctx (also from buttons); False if there is no such action
    action = self.actions.get(name)
    if action is None:
      return False
    #
    if ctx.role < action.role:
      await ctx.reply('You need to be ' + roles.NAMES[action.role] + ' for /admin ' + name + '.')
      return True
    #
    try:
      await action.handler(ctx)
    except commands.UsageError as exc:
      prefix = '/' if ctx.source == commands.GAME else '!'
      await ctx.reply((str(exc) + ' ' if str(exc) else '') + 'Usage: ' + prefix + 'admin ' + name
        + (' ' + action.usage if action.usage else ''))
    #
    return True
  #

  async def cmd_admin(self, ctx):
    if ctx.args:
      name, ctx.args = ctx.args[0].lower(), ctx.args[1:]
      if await self.run(ctx, name):
        return
      #
      await ctx.reply('There is no admin action ' + name + '.')
    #
    prefix = '/' if ctx.source == commands.GAME else '!'
    lines = [(prefix + 'admin ' + a.name + (' ' + a.usage if a.usage else ''), a.help) for a in self.available(ctx.role)]
    if ctx.source == commands.GAME:
      await self.window.open(ctx.login, 'Admin actions', [('$fff' + c, '$ddd' + h) for c, h in lines])
    else:
      await ctx.reply('\n'.join(c + ' - ' + h for c, h in lines))
    #
  #
#
