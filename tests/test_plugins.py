import asyncio

from core import roles
from conftest import Harness


def run(coro):
  return asyncio.run(coro)
#


def test_welcome_messages(tmp_path):
  async def scenario():
    config = '[welcome]\nleave = ""\njoin = "{nickname}$z$s ({role}, {visits_text}) {typo}"\n'
    async with Harness(tmp_path, config, plugins=('welcome',)) as h:
      await h.join('ann', '$f0fAnn')
      assert h.replies_to('ann')[-1].endswith('Welcome $f0fAnn$z$s to Fake Server$z$s! Type $fff/pyseco$z$s for the commands.')
      assert h.announcements()[-1].endswith('$f0fAnn$z$s (player, first visit) {typo}')
      await h.leave('ann')
      count = len(h.announcements())
      await h.join('ann', '$f0fAnn')
      assert h.announcements()[-1].endswith('(player, visit 2) {typo}')
      assert len(h.announcements()) == count + 1 # leave is switched off
    #
  #
  run(scenario())
#


def test_flexitime_counts_down_and_skips(tmp_path):
  async def scenario():
    config = '[flexitime]\nminutes = 3\n[widgets.flexitime]\nx = -60\ny = 10.5\n'
    async with Harness(tmp_path, config, plugins=('flexitime',), timer=False) as h:
      assert h.server.called('SetTimeAttackLimit') == [(0,)] # the server's limit is switched off
      assert h.server.called('ChallengeRestart') # nobody on the server: at once
      flexi = h.plugin('flexitime')
      assert flexi.left == 180
      await h.join('adm')
      await h.controller.accounts.set_role('adm', roles.ADMIN)
      clock = h.server.called('SendDisplayManialinkPageToLogin')[-1]
      assert clock[0] == 'adm' and '3:00' in clock[1] # a joining player sees the clock right away
      assert '<frame posn="-60.0 10.5 10">' in clock[1] # moved in the settings

      announced = len(h.announcements())
      await h.tick(60)
      assert '2:00' in h.server.called('SendDisplayManialinkPage')[-1][0]
      assert len(h.announcements()) == announced # no warnings in the chat

      await h.chat('bob', '/timeleft')
      assert h.replies_to('bob')[-1].endswith('Time left on this map: $fff2:00$z$s.')
      await h.chat('bob', '/timeleft 10')
      assert 'You need to be admin' in h.replies_to('bob')[-1]
      await h.chat('adm', '/timeleft +1.5')
      assert flexi.left == 210 and 'set the time left to $fff3:30' in h.announcements()[-1]
      await h.chat('adm', '/timeleft pause')
      await h.tick(5)
      assert flexi.left == 210 and 'paused' in h.server.called('SendDisplayManialinkPage')[-1][0]
      await h.chat('adm', '/timeleft resume')
      await h.chat('adm', '/timeleft 0.1')
      assert flexi.left == 6
      await h.chat('adm', '/timeleft soon')
      assert 'Usage' in h.replies_to('adm')[-1]

      await h.tick(6)
      assert 'Time is up' in h.announcements()[-1] and h.server.called('NextChallenge')
      assert flexi.left is None
      await h.server.play_next(race=False)
      await h.settle()
      await h.tick(5)
      assert flexi.left == 180 # the map is loading, the time doesn't run yet
      await h.server.callback('TrackMania.StatusChanged', 4, 'Running - Play')
      await h.settle()
      await h.tick(5)
      assert flexi.left == 175
    #
  #
  run(scenario())
#


def test_flexitime_only_in_time_attack(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=('flexitime',), timer=False) as h:
      h.server.handlers['GetGameMode'] = lambda: 0 # rounds
      await h.server.play_next()
      await h.settle()
      assert h.plugin('flexitime').left is None
      await h.chat('bob', '/timeleft')
      assert 'no time limit' in h.replies_to('bob')[-1]
    #
  #
  run(scenario())
#


def test_flexitime_does_not_restart_a_map_with_players(tmp_path):
  async def scenario():
    from fake_server import FakeServer
    server = FakeServer()
    server.players['ann'] = {'Login': 'ann', 'NickName': 'Ann', 'PlayerId': 2, 'TeamId': -1, 'SpectatorStatus': 0,
      'LadderRanking': 0, 'Flags': 0}
    async with Harness(tmp_path, plugins=('flexitime',), server=server, timer=False) as h:
      assert h.server.called('SetTimeAttackLimit') == [(0,)]
      assert not h.server.called('ChallengeRestart')
    #
  #
  run(scenario())
#
