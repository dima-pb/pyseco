import xmlrpc.client

from core import commands, log, roles
from core.server import request_xml
from plugins.plugin import Plugin


class CustomVote(Plugin):
  # /skip and /replay as votes of the server's own voting engine. The vote carries an Echo call;
  # when it passes, the server executes the Echo and the plugin reacts to the Echo callback.
  #
  # Settings ([custom_votes] in pyseco.toml):
  #   timeout = 30000   vote duration in ms
  #   ratio = 0.5       share of yes votes needed

  def __init__(self, controller):
    super().__init__(controller)

    settings = controller.settings('custom_votes')
    self.timeout = int(settings.get('timeout', 30000))
    self.ratio = float(settings.get('ratio', 0.5))

    self.callvotes = {
      'replay': ['Replay this map', self.replay_map],
      'skip': ['Skip this map', self.skip_map],
    }

    controller.commands.register('replay', self.vote_replay, help='starts a vote to replay this map',
      sources=(commands.GAME,), aliases=('res', 'restart'))
    controller.commands.register('skip', self.vote_skip, help='starts a vote to skip this map',
      sources=(commands.GAME,), aliases=('next',))
    controller.events.register('TrackMania.Echo', self.echo)
  #

  async def start(self):
    server = self.controller.server
    await server.set_call_vote_time_out(self.timeout)
    # disable the native votes, they are replaced by the chat commands of this plugin
    await server.set_call_vote_ratios([
      { 'Command': 'ChallengeRestart', 'Ratio': -1.0 },
      { 'Command': 'NextChallenge', 'Ratio': -1.0 },
    ])
  #

  async def vote_replay(self, ctx):
    await self.start_vote('replay')
  #
  
  async def vote_skip(self, ctx):
    await self.start_vote('skip')
  #
  
  async def start_vote(self, vote):
    description = self.callvotes[vote][0]
    # the server swaps the Echo parameters: the callback arrives as (vote, description)
    echo = request_xml('Echo', description, vote)
    try:
      await self.controller.server.call_vote_ex(echo, self.ratio, self.timeout, 1)
    except xmlrpc.client.Fault as exc:
      self.controller.logger.message(str(exc), log.LOG_ERROR)
    #
  #

  async def echo(self, params):
    cmd_str = params[0]
    msg = params[1]
    if cmd_str not in self.callvotes:
      return
    #

    await self.controller.chat.send_raw('Vote: "' + msg + '" passed')
    await self.callvotes[cmd_str][1]()
  #

  async def replay_map(self):
    map = await self.controller.server.get_current_challenge_info()
    jukebox = self.controller.plugins.get('jukebox')
    if jukebox is None:
      await self.controller.server.choose_next_challenge(map['FileName'])
      return
    #
    # through the jukebox, which decides the next map; first in the queue
    # TODO: reaches into another plugin; goes through the playlist service once it exists
    from plugins.jukebox import Entry
    await jukebox.add(Entry.from_map(map, source='Replay'), roles.ADMIN, jukebox.no_reply, front=True)
  #

  async def skip_map(self):
    await self.controller.server.next_challenge()
  #
#
