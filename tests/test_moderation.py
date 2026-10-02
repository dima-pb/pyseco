import asyncio

from core import roles
from conftest import Harness, action_of, texts


def run(coro):
  return asyncio.run(coro)
#


def test_kick_mute_and_roles(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      await h.controller.accounts.set_role('op', roles.OPERATOR)
      await h.join('op', '$00fOp')
      await h.join('troll', '$f00The Troll')
      await h.join('trolley')

      await h.chat('troll', '/kick op')
      assert 'You need to be operator' in h.replies_to('troll')[-1]
      await h.chat('op', '/kick trol')
      assert 'Several players match "trol": troll, trolley.' in h.replies_to('op')[-1]
      await h.chat('op', '/kick master')
      assert 'No player on the server matches' in h.replies_to('op')[-1]

      await h.chat('op', '/mute the troll') # part of the nickname, colors don't matter
      assert h.server.called('Ignore')[-1] == ('troll',)
      assert 'muted $fff$f00The Troll' in h.announcements()[-1]
      await h.chat('op', '/kick the spamming')
      assert 'No player' in h.replies_to('op')[-1]
      await h.chat('op', '/kick trolley go away')
      assert h.server.called('Kick')[-1] == ('trolley', 'You were kicked by Op: go away')
      assert 'trolley' not in h.controller.players.online

      # muted players stay muted when they come back
      await h.leave('troll')
      await h.join('troll', '$f00The Troll')
      assert h.server.called('Ignore')[-1] == ('troll',)
      await h.chat('op', '/unmute troll')
      assert h.server.called('UnIgnore')[-1] == ('troll',)

      # nobody acts on the same or a higher role
      await h.controller.accounts.set_role('op2', roles.OPERATOR)
      await h.join('op2')
      await h.chat('op', '/kick op2')
      assert 'their role is not below yours' in h.replies_to('op')[-1]
      await h.chat('op', '/kick op')
      assert 'yourself' in h.replies_to('op')[-1]
    #
  #
  run(scenario())
#


def test_bans_are_kept_and_enforced(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      await h.controller.accounts.set_role('adm', roles.ADMIN)
      await h.join('adm')
      await h.join('cheater')
      await h.chat('adm', '/ban cheater 2h speed hack')
      assert h.server.called('Kick')[-1][0] == 'cheater' and 'speed hack' in h.server.called('Kick')[-1][1]
      ban = await h.controller.storage.moderation.ban_of('cheater')
      assert ban.reason == 'speed hack' and ban.until is not None and ban.by == 'adm'

      await h.chat('adm', '/ban offline_guy') # not on the server: the login, for ever
      assert (await h.controller.storage.moderation.ban_of('offline_guy')).until is None

      # banned players are kicked when they connect
      kicks = len(h.server.called('Kick'))
      await h.join('cheater')
      assert len(h.server.called('Kick')) == kicks + 1 and 'You are banned' in h.server.called('Kick')[-1][1]

      await h.chat('adm', '/bans')
      shown = texts(h.manialink('adm'))
      assert '$fffcheater' in shown and '$fffoffline_guy' in shown and '$dddspeed hack' in shown
      await h.chat('adm', '/unban cheater')
      assert 'no longer banned' in h.replies_to('adm')[-1]
      assert await h.controller.storage.moderation.ban_of('cheater') is None
      await h.chat('adm', '/unban cheater')
      assert 'is not banned' in h.replies_to('adm')[-1]
    #
  #
  run(scenario())
#


def test_players_window_and_actions(tmp_path):
  async def scenario():
    async with Harness(tmp_path) as h:
      await h.controller.accounts.set_role('op', roles.OPERATOR)
      await h.join('op', 'Op')
      await h.join('bob', 'Bob')
      await h.chat('bob', '/players')
      page = h.manialink('bob')
      assert '$fffBob' in texts(page) and '$dddoperator' in texts(page)
      assert not [q for q in page.iter('quad') if q.get('action') and q.get('substyle') == 'BgCardSystem']

      await h.chat('op', '/players')
      await h.click('op', action_of(h.manialink('op'), '$fffBob'))
      page = h.manialink('op')
      assert texts(page)[:3] == ['$fffBob', '$fffKick', '$fffMute'] and '$fffBan for ever' not in texts(page)
      await h.click('op', action_of(page, '$fffMute'))
      assert await h.controller.storage.moderation.muted() == {'bob'}
      assert h.manialink('op') is None

      await h.controller.accounts.set_role('adm', roles.ADMIN)
      await h.join('adm', 'Adm')
      await h.chat('adm', '/players')
      await h.click('adm', action_of(h.manialink('adm'), '$fffBob'))
      page = h.manialink('adm')
      assert '$fffUnmute' in texts(page)
      await h.click('adm', action_of(page, '$fffBan for 1 day'))
      assert (await h.controller.storage.moderation.ban_of('bob')).until is not None
      assert 'bob' not in h.controller.players.online
    #
  #
  run(scenario())
#
