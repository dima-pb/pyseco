import re
import xmlrpc.client

from core import commands, events, log, roles
from plugins.plugin import Plugin
from services.windows import TextWidget


TIME_ATTACK = 1
MAX_SECONDS = 12 * 3600
TIME = re.compile(r'^([+-]?)(\d+)(?:[.,:](\d+))?$')
STATUS_PLAY = 4 # 'Running - Play': the race runs (before: loading, synchronization)


def clock(seconds):
  # 3725 -> '1:02:05', 125 -> '2:05'
  hours, rest = divmod(max(seconds, 0), 3600)
  minutes, seconds = divmod(rest, 60)
  return (str(hours) + ':' + str(minutes).zfill(2) if hours else str(minutes)) + ':' + str(seconds).zfill(2)
#


def parse_time(text):
  # '30' -> ('', 1800), '+1.30' / '+1,30' / '+1:30' -> ('+', 90): minutes, optionally with seconds after the separator;
  # raises UsageError with what is wrong
  match = TIME.match(text)
  if not match:
    raise commands.UsageError()
  #
  sign, minutes, seconds = match.group(1), int(match.group(2)), match.group(3)
  if seconds is not None and (len(seconds) != 2 or int(seconds) > 59):
    raise commands.UsageError('Seconds come as two digits from 00 to 59 after the separator, e.g. 1.05 or 1.50.')
  #
  return sign, minutes * 60 + int(seconds or 0)
#


class Flexitime(Plugin):
  # The time limit of a map, run by pyseco instead of the server, so admins can change it while the map
  # is played. When the time is up, the next map starts. A clock shows the time left; admins click it to pause
  # the time or let it run again. Only in time attack.
  # The time runs from the start of the race on, not while the map loads.
  # The server's own time limit is switched off (it takes effect from the next map on).
  #
  # Settings ([flexitime] in pyseco.toml):
  #   minutes = 60             time per map
  # The clock is the widget "flexitime", it can be moved with [widgets.flexitime] (see services/windows.py).

  def __init__(self, controller):
    super().__init__(controller)
    settings = controller.settings('flexitime')
    self.minutes = float(settings.get('minutes', 60))
    # below the server's box with the previous and best time
    self.widget = TextWidget(controller.ui, 'flexitime', x=49, y=32, width=14, height=4.5, size=3,
      on_click=self.clicked)
    self.left = None # seconds left on this map, None while no map is timed (podium, other game modes)
    self.paused = False
    self.racing = False # the race runs, the time counts

    controller.events.register(events.MAP_STARTED, self.map_started)
    controller.events.register('TrackMania.StatusChanged', self.status_changed)
    controller.events.register(events.MAP_ENDED, self.map_ended)
    controller.events.register(events.SECOND_PASSED, self.second_passed)
    controller.events.register(events.PLAYER_JOINED, self.player_joined)
    controller.commands.register('timeleft', self.cmd_timeleft, help='shows the time left on this map; admins change it',
      usage='[<min>[.<sec>] | +<min>[.<sec>] | -<min>[.<sec>] | pause | resume]')
  #

  async def start(self):
    server = self.controller.server
    limit = await server.get_time_attack_limit()
    if limit['NextValue'] != 0:
      await server.set_time_attack_limit(0)
      self.log('The server\'s time limit is switched off, flexitime keeps the time')
    #
    if limit['CurrentValue'] != 0:
      # the server takes the change with the next map; nobody there (e.g. right after the server started): now
      if not self.controller.players.online:
        self.log('Restarting the map, so the server\'s own time limit is gone right away')
        await server.challenge_restart()
      else:
        self.log('The server\'s own time limit still runs on this map, from the next map on only flexitime')
      #
    #
    if self.controller.maps.current is not None:
      await self.map_started(self.controller.maps.current)
      self.racing = (await server.get_status())['Code'] == STATUS_PLAY
    #
  #

  async def stop(self):
    await self.widget.hide()
  #

  def log(self, text, level=log.LOG_INFO):
    self.controller.logger.message('[flexitime] ' + text, level)
  #

  def time_text(self):
    if self.left is None:
      return ''
    #
    color = '$f44' if self.left <= 60 else '$fc0' if self.left <= 300 else '$fff'
    return color + ('$o' if self.left <= 60 else '') + clock(self.left) + ('$z$s $999paused' if self.paused else '')
  #

  async def show(self, login=None):
    if self.left is None:
      await self.widget.hide(login)
    else:
      await self.widget.show(self.time_text(), login)
    #
  #

  async def map_started(self, map):
    try:
      mode = await self.controller.server.get_game_mode()
    except xmlrpc.client.Fault:
      mode = TIME_ATTACK
    #
    self.left = int(self.minutes * 60) if mode == TIME_ATTACK else None
    self.paused = False
    self.racing = False
    await self.show()
  #

  async def status_changed(self, params):
    self.racing = params[0] == STATUS_PLAY
  #

  async def map_ended(self, map):
    self.left = None
    await self.show()
  #

  async def player_joined(self, player):
    if self.left is not None:
      await self.show(player.login)
    #
  #

  async def second_passed(self, _):
    if self.left is None or self.paused or not self.racing:
      return
    #
    self.left -= 1
    if self.left <= 0:
      self.left = None
      await self.show()
      await self.controller.chat.announce('Time is up, next map.')
      await self.controller.server.next_challenge()
      return
    #
    await self.show()
  #

  async def clicked(self, login):
    # a click on the clock pauses the time or lets it run again, like /timeleft pause / resume (admins)
    player = self.controller.players.online.get(login)
    ctx = commands.Context(commands.GAME, login, player.nickname if player else login,
      await self.controller.accounts.role(login), ['resume' if self.paused else 'pause'],
      lambda text: self.controller.chat.tell(login, text))
    await self.cmd_timeleft(ctx)
  #

  async def cmd_timeleft(self, ctx):
    if not ctx.args:
      if self.left is None:
        await ctx.reply('This map has no time limit right now.')
      else:
        await ctx.reply('Time left on this map: $fff' + clock(self.left) + '$z$s' + (' (paused)' if self.paused else '') + '.')
      #
      return
    #
    if ctx.role < roles.ADMIN:
      await ctx.reply('You need to be admin to change the time.')
      return
    #
    if self.left is None:
      await ctx.reply('This map has no time limit right now.')
      return
    #
    arg = ctx.args[0].lower()
    if len(ctx.args) != 1:
      raise commands.UsageError()
    #
    if arg in ('pause', 'resume'):
      self.paused = arg == 'pause'
      text = 'paused the time' if self.paused else 'let the time run again'
    else:
      sign, seconds = parse_time(arg)
      left = self.left + seconds if sign == '+' else self.left - seconds if sign == '-' else seconds
      if left < 1:
        await ctx.reply('That leaves no time: only $fff' + clock(self.left) + '$z$s are left.' if sign == '-'
          else 'The time must be more than 0.')
        return
      #
      if left > MAX_SECONDS:
        await ctx.reply('At most 12 hours, the time is set to 12 hours.')
        left = MAX_SECONDS
      #
      self.left = left
      text = 'set the time left to $fff' + clock(self.left) + '$z$s'
    #
    self.log(ctx.login + ' ' + text)
    await self.controller.chat.announce('$fff' + ctx.display_name + '$z$s ' + text + '.')
    await self.show()
  #
#
