import asyncio

from conftest import Harness, action_of, texts


def run(coro):
  return asyncio.run(coro)
#


def test_voting_in_chat_and_widget(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=('karma', 'jukebox')) as h:
      karma = h.plugin('karma')
      for login in ('ann', 'bob', 'cid'):
        await h.join(login, login.capitalize())
      #
      assert '$999no votes yet' in texts(h.manialink('ann', karma.id))

      await h.chat('ann', '++') # plain chat
      await h.chat('bob', '/--') # command
      await h.chat('cid', '++')
      await h.settle()
      assert h.replies_to('ann')[-1].endswith('You rated this map $0f0++$z$s.')
      widget = texts(h.manialink('bob', karma.id))
      assert '$fff67%  $0f0+2 $f44-1' in widget
      quads = list(h.manialink('bob', karma.id).iter('quad'))
      assert quads[2].get('substyle') == 'BgCardSystem' and quads[3].get('substyle') == 'BgTitle3_1' # bob's -- stands out

      await h.click('bob', karma.first_action) # bob changes his mind: ++
      assert '$fff100%  $0f0+3 $f44-0' in texts(h.manialink('ann', karma.id))
      await h.chat('bob', '++')
      assert 'already' in h.replies_to('bob')[-1]
      await h.click('cid', karma.first_action) # cid clicks his ++ again: taken back
      assert 'taken back' in h.replies_to('cid')[-1] and '$fff100%  $0f0+2 $f44-0' in texts(h.manialink('ann', karma.id))
      await h.click('cid', karma.first_action) # and votes again

      assert await h.controller.karma.counts(['uid1']) == {'uid1': (3, 0)}

      await h.click('ann', karma.first_action + 2) # the title opens who voted
      shown = texts(h.manialink('ann'))
      assert shown[0] == '$fffKarma of Map 1: 100%' and shown.count('$0f0++') == 3

      await h.chat('ann', '/list') # the map list shows the votes
      assert '$0f0+3 $f44-0' in texts(h.manialink('ann'))

      await h.server.play_next() # another map, no votes yet
      await h.settle()
      assert '$999no votes yet' in texts(h.manialink('ann', karma.id))
    #
  #
  run(scenario())
#
