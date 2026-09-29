import accounts
import commands
import log
from plugins.plugin import Plugin
import messages


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
    controller.register_event('TrackMania.Echo', self.echo)
  #

  async def start(self):
    await self.controller.set_callvote_timeout(self.timeout)
    # disable the native votes, they are replaced by the chat commands of this plugin
    await self.controller.set_callvote_ratios((
      { 'Command': 'ChallengeRestart', 'Ratio': -1.0 },
      { 'Command': 'NextChallenge', 'Ratio': -1.0 },
    ))
  #

  async def vote_replay(self, ctx):
    await self.start_vote('replay')
  #
  
  async def vote_skip(self, ctx):
    await self.start_vote('skip')
  #
  
  async def start_vote(self, vote):
    description = self.callvotes[vote][0]
    echo = messages.Echo(vote, description)
    try:
      await self.controller.call_vote_ex(echo, self.ratio, self.timeout, 1)
    except Exception as exc:
      self.controller.logger.message(str(exc), log.LOG_ERROR)
    #
  #

  async def echo(self, params):
    cmd_str = params[0]
    msg = params[1]
    if cmd_str not in self.callvotes:
      return
    #

    await self.controller.chat_send_server_message('Vote: "' + msg + '" passed')
    await self.callvotes[cmd_str][1]()
  #

  async def replay_map(self):
    map = await self.controller.get_current_challenge_info()
    jukebox = self.controller.plugins.get('jukebox')
    if jukebox is None:
      await self.controller.choose_next_challenge(map['FileName'])
      return
    #
    # through the jukebox, which decides the next map; first in the queue
    from plugins.jukebox import Entry
    await jukebox.add(Entry.from_map(map, source='Replay'), accounts.ADMIN, jukebox.no_reply, front=True)
  #

  async def skip_map(self):
    await self.controller.next_challenge()
  #
#
