from core import commands, roles
from core.text import strip_colors
from plugins.plugin import Plugin
from services.playlist import Entry, PlaylistError
from services.windows import ListWindow


LIST_PAGE = 8


class Jukebox(Plugin):
  # Players wish maps from the server's list (/list, /jukebox <number>). The wishes go to the playlist, which
  # decides what comes next; the jukebox only adds its rules for players.
  #
  # Settings ([jukebox] in pyseco.toml):
  #   recent = 10       players can't wish one of the last <recent> maps (operators and above can)
  #   per_player = 1    wishes per player in the queue at a time (operators and above: no limit)

  def __init__(self, controller):
    super().__init__(controller)
    settings = controller.settings('jukebox')
    self.recent = int(settings.get('recent', 10))
    self.per_player = int(settings.get('per_player', 1))
    self.playlist = controller.playlist
    self.list_window = ListWindow(controller.ui, width=90, columns=[7, 50, 29])
    self.queue_window = ListWindow(controller.ui, width=90, columns=[7, 50, 29])

    register = controller.commands.register
    register('list', self.cmd_list, help='lists the maps on the server', usage='[page | search text]')
    register('jukebox', self.cmd_jukebox, help='wishes the map with this number (see /list) to be played next',
      usage='[<number> | list | drop | drop <position> | clear]', aliases=('jb',))
  #


  # ---- wishes ----

  async def wish(self, login, display_name, role, m, reply):
    # checks the rules for players, then asks the playlist; reply(text) tells the player why not
    if role < roles.OPERATOR:
      if sum(1 for e in self.playlist.queue if e.login == login) >= self.per_player:
        await reply('You already have a map in the jukebox (/jukebox drop removes it).')
        return False
      #
      # the current map counts as played (a replay goes through the vote)
      if m['UId'] in [uid for uid, _, _ in await self.controller.maps.history(self.recent + 1)]:
        await reply('This map was played recently, choose another one.')
        return False
      #
    #
    player = self.controller.players.online.get(login)
    entry = Entry.from_map(m, login, player.nickname if player else display_name)
    try:
      await self.playlist.request(entry)
    except PlaylistError as exc:
      await reply(str(exc))
      return False
    #
    await self.controller.chat.announce('$fff' + strip_colors(entry.name) + '$z$s was added to the jukebox by $fff'
      + entry.requested_by() + '$z$s.')
    return True
  #

  async def wish_from_window(self, login, uid):
    reply = lambda text: self.controller.chat.tell(login, text)
    m = self.controller.maps.by_uid.get(uid)
    if m is None:
      await reply('This map is no longer on the server.')
      return
    #
    if await self.wish(login, login, await self.controller.accounts.role(login), m, reply):
      await self.list_window.close(login)
    #
  #


  # ---- commands ----

  def map_line(self, index, m):
    return str(index + 1) + '. $fff' + strip_colors(m['Name']) + '$z$s by ' + (m.get('Author') or '?')
  #

  async def cmd_list(self, ctx):
    maps = list(enumerate(self.controller.maps.list))
    page = 1
    if len(ctx.args) == 1 and ctx.args[0].isdigit():
      page = int(ctx.args[0])
    elif ctx.args:
      words = [w.lower() for w in ctx.args]
      maps = [(i, m) for i, m in maps if all(w in (strip_colors(m['Name']) + ' ' + m.get('Author', '')).lower()
        for w in words)]
      if not maps:
        await ctx.reply('No map matches "' + ' '.join(ctx.args) + '".')
        return
      #
    #
    if ctx.source == commands.GAME:
      rows = [('$ddd' + str(i + 1) + '.', '$fff' + strip_colors(m['Name']), '$ddd' + (m.get('Author') or '?'))
        for i, m in maps]
      uids = [m['UId'] for i, m in maps]
      async def wish(login, index):
        await self.wish_from_window(login, uids[index])
      #
      searched = ctx.args and not (len(ctx.args) == 1 and ctx.args[0].isdigit())
      title = 'Maps' + (' matching "' + ' '.join(ctx.args) + '"' if searched else '')
      await self.list_window.open(ctx.login, title, rows, wish, page - 1, hint='Click a map to wish it')
      return
    #
    pages = max(1, (len(maps) + LIST_PAGE - 1) // LIST_PAGE)
    page = min(max(page, 1), pages)
    shown = maps[(page - 1) * LIST_PAGE:page * LIST_PAGE]
    await ctx.reply('Maps ' + str(page) + '/' + str(pages) + ' (!jukebox <number> to wish one, !list <page> for more):')
    for i, m in shown:
      await ctx.reply(self.map_line(i, m))
    #
  #

  async def cmd_jukebox(self, ctx):
    queue = self.playlist.queue
    args = [a.lower() for a in ctx.args]
    if not args or args == ['list']:
      if ctx.source == commands.GAME:
        rows = [('$ddd' + str(i + 1) + '.', '$fff' + strip_colors(e.name), '$ddd' + e.requested_by())
          for i, e in enumerate(queue)]
        await self.queue_window.open(ctx.login, 'Jukebox', rows, hint='/jukebox drop removes your wish')
      elif not queue:
        await ctx.reply('The jukebox is empty.')
      else:
        await ctx.reply('\n'.join(str(i + 1) + '. ' + strip_colors(e.name) + ' (' + e.requested_by() + ')'
          for i, e in enumerate(queue)))
      #
    elif args[0].isdigit() and len(args) == 1:
      if ctx.login is None:
        await ctx.reply('Link your discord account first (/link in game).')
        return
      #
      number = int(args[0])
      if not 1 <= number <= len(self.controller.maps.list):
        await ctx.reply('There is no map ' + args[0] + ', see /list.')
        return
      #
      await self.wish(ctx.login, ctx.display_name, ctx.role, self.controller.maps.list[number - 1], ctx.reply)
    elif args == ['drop']:
      index = next((i for i, e in enumerate(queue) if ctx.login and e.login == ctx.login), None)
      if index is None:
        await ctx.reply('You have no map in the jukebox.')
      else:
        entry = await self.playlist.remove(index)
        await ctx.reply('Removed ' + strip_colors(entry.name) + ' from the jukebox.')
      #
    elif args[0] == 'drop' and len(args) == 2 and args[1].isdigit() and ctx.role >= roles.OPERATOR:
      position = int(args[1])
      if not 1 <= position <= len(queue):
        await ctx.reply('The jukebox has no position ' + args[1] + '.')
        return
      #
      entry = await self.playlist.remove(position - 1)
      await self.controller.chat.announce('$fff' + strip_colors(entry.name) + '$z$s was removed from the jukebox.')
    elif args == ['clear'] and ctx.role >= roles.ADMIN:
      await self.playlist.clear()
      await self.controller.chat.announce('The jukebox was cleared.')
    else:
      raise commands.UsageError()
    #
  #
#
