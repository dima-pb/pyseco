import xmlrpc.client

from core import commands, events, log
from services.windows import ListWindow


PREFIX = '$fb0»$z$s '


class Chat:
  # Messages from pyseco to the players, and the game side of commands: chat starting with / runs the
  # registered command, other chat of players is raised as events.CHAT. /pyseco shows the commands.
  # Sending never raises: a message that can't be sent is logged, the caller goes on.

  def __init__(self, controller):
    self.controller = controller
    controller.events.register('TrackMania.PlayerChat', self.player_chat)
    self.help_window = ListWindow(controller.ui, width=100, columns=[34, 62])
    controller.commands.register('pyseco', self.cmd_help, help='lists the pyseco commands you can use',
      sources=(commands.GAME,))
  #

  async def announce(self, text):
    # to everybody, marked as from pyseco
    await self.send_raw(PREFIX + text)
  #

  async def tell(self, login, text):
    # only this player (or a comma-separated list of logins) sees it
    try:
      await self.controller.server.chat_send_server_message_to_login(PREFIX + text, login)
    except (xmlrpc.client.Fault, ConnectionError) as exc:
      self.controller.logger.message('Chat message to ' + login + ' failed: ' + str(exc), log.LOG_WARNING)
    #
  #

  async def send_raw(self, text):
    # to everybody, exactly as given
    try:
      await self.controller.server.chat_send_server_message(text)
    except (xmlrpc.client.Fault, ConnectionError) as exc:
      self.controller.logger.message('Chat message failed: ' + str(exc), log.LOG_WARNING)
    #
  #

  async def player_chat(self, params):
    uid, login, text = params[0], params[1], params[2].strip()
    if uid == 0: # the server's own messages
      return
    #
    player = await self.controller.players.get(login)
    if not text.startswith('/'):
      if player is not None:
        await self.controller.events.emit(events.CHAT, events.ChatMessage(player, text))
      #
      return
    #
    # /name args -> registered command; unknown commands are left alone (the server or others may know them)
    words = text[1:].split()
    if not words:
      return
    #
    ctx = commands.Context(commands.GAME, login, player.nickname if player else login,
      await self.controller.accounts.role(login), words[1:], lambda reply: self.tell(login, reply))
    await self.controller.commands.run(ctx, words[0])
  #

  async def cmd_help(self, ctx):
    rows = [('$fff/' + c.name + (' ' + c.usage if c.usage else ''), '$ddd' + c.help)
      for c in self.controller.commands.available(ctx.role, ctx.source)]
    await self.help_window.open(ctx.login, 'pyseco commands', rows)
  #
#
