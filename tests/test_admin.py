import asyncio

from core import roles
from conftest import Harness, action_of, texts
from services.playlist import Entry


def run(coro):
  return asyncio.run(coro)
#


def test_admin_actions(tmp_path):
  async def scenario():
    async with Harness(tmp_path, '[maps]\nmatchsettings = "MatchSettings/active.txt"\n') as h:
      await h.controller.accounts.set_role('op', roles.OPERATOR)
      await h.chat('bob', '/admin next')
      assert 'You need to be operator' in h.replies_to('bob')[-1]

      await h.chat('op', '/admin')
      shown = texts(h.manialink('op'))
      assert '$fff/admin next' in shown and '$fff/admin remove [<number in /list>]' not in shown # admins only

      await h.chat('op', '/admin replay')
      assert [e.uid for e in h.controller.playlist.queue] == ['uid1'] and 'once more' in h.announcements()[-1]
      await h.chat('op', '/admin restart')
      assert h.server.called('ChallengeRestart')
      await h.chat('op', '/admin next')
      assert h.server.called('NextChallenge')
      await h.chat('op', '/admin dance')
      assert 'There is no admin action dance.' in h.replies_to('op')[-1]
      await h.chat('op', '/admin remove')
      assert 'You need to be admin for /admin remove.' in h.replies_to('op')[-1]

      await h.chat('master', '/admin remove 3')
      assert h.server.called('RemoveChallenge') == [('Challenges\\Map3.Challenge.Gbx',)]
      assert h.server.called('SaveMatchSettings') == [('MatchSettings/active.txt',)]
      assert 'removed $fffMap 3$z$s from the map list' in h.announcements()[-1]
      await h.chat('master', '/admin remove 99')
      assert 'There is no map 99' in h.replies_to('master')[-1]

      # a removed map that was requested leaves the queue
      await h.controller.playlist.request(Entry.from_map(h.server.maps[2])) # Map 4, number 3 now
      await h.chat('master', '/admin remove 3')
      await h.settle()
      assert 'uid4' not in [e.uid for e in h.controller.playlist.queue]
    #
  #
  run(scenario())
#


def test_without_matchsettings_removing_is_not_saved(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      await h.chat('master', '/admin remove')
      assert h.server.called('RemoveChallenge') == [('Challenges\\Map1.Challenge.Gbx',)] # the current map
      assert 'Not saved' in h.replies_to('master')[-1] and not h.server.called('SaveMatchSettings')
    #
  #
  run(scenario())
#


def test_admin_panel(tmp_path):
  async def scenario():
    async with Harness(tmp_path, '[maps]\nmatchsettings = "MatchSettings/active.txt"\n', plugins=('admin_panel',)) as h:
      panel = h.plugin('admin_panel')
      await h.join('bob')
      assert h.manialink('bob', panel.id) is None # players see no buttons
      await h.controller.accounts.set_role('op', roles.OPERATOR)
      await h.join('op')
      assert texts(h.manialink('op', panel.id)) == ['$fffNext', '$fffReplay', '$fffRestart'] # no Remove for operators
      await h.join('master')
      assert texts(h.manialink('master', panel.id))[-1] == '$fffRemove'

      await h.chat('master', '/setrole bob operator') # the panel follows the role
      assert texts(h.manialink('bob', panel.id)) == ['$fffNext', '$fffReplay', '$fffRestart']

      await h.click('op', panel.first_action + 1) # replay: at once
      assert [e.uid for e in h.controller.playlist.queue] == ['uid1']
      await h.click('op', action_of(h.manialink('op', panel.id), 'BgCardSystem')) # the first button: next, asks
      assert texts(h.manialink('op'))[0] == '$fffSkip to the next map?' and not h.server.called('NextChallenge')
      await h.click('op', action_of(h.manialink('op'), '$fffYes, next map'))
      assert h.server.called('NextChallenge')
      await h.click('op', panel.first_action + 2) # restart, asks
      assert texts(h.manialink('op'))[0] == '$fffRestart Map 1?'
      await h.click('op', action_of(h.manialink('op'), '$fffNo'))
      assert not h.server.called('ChallengeRestart')
      await h.click('master', panel.first_action + 3) # remove: asks first
      page = h.manialink('master')
      assert texts(page)[0] == '$fffRemove Map 1?'
      await h.click('master', action_of(page, '$fffNo'))
      assert not h.server.called('RemoveChallenge')
      await h.click('master', panel.first_action + 3)
      await h.click('master', action_of(h.manialink('master'), '$fffYes, remove it from the map list'))
      assert h.server.called('RemoveChallenge') == [('Challenges\\Map1.Challenge.Gbx',)]
    #
  #
  run(scenario())
#


def test_a_refusing_server_is_told(tmp_path):
  async def scenario():
    import xmlrpc.client
    async with Harness(tmp_path) as h:
      def busy():
        raise xmlrpc.client.Fault(-1000, 'Change in progress.')
      #
      h.server.handlers['NextChallenge'] = busy
      count = len(h.announcements())
      await h.chat('master', '/admin next')
      assert h.replies_to('master')[-1].endswith('The server refused: Change in progress. Try again in a moment.')
      assert len(h.announcements()) == count # nothing announced
    #
  #
  run(scenario())
#
