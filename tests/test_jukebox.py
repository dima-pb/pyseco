import asyncio
import json
import re

from core import roles
from conftest import Harness, action_of, texts

PLUGINS = ('jukebox', 'custom_votes')


def run(coro):
  return asyncio.run(coro)
#


def next_file(h):
  return h.server.maps[h.server.next]['FileName']
#


async def queue_uids(h):
  return [e.uid for e in h.plugin('jukebox').queue]
#


def test_list_window_pages_search_and_wish(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=PLUGINS) as h:
      h.server.maps += [h.server.make_map(i) for i in range(6, 21)] # 20 maps, 15 per page
      await h.controller.maps.refresh()
      await h.chat('bob', '/list')
      page = h.manialink('bob')
      assert '$fffMap 1' in texts(page) and '$fffMap 16' not in texts(page)
      assert '$fff1 / 2' in texts(page) and '$bbbClick a map to wish it' in texts(page)
      await h.click('bob', action_of(page, 'ArrowNext'))
      page = h.manialink('bob')
      assert '$fffMap 16' in texts(page) and '$ddd16.' in texts(page)

      await h.chat('bob', '/list map 1')
      page = h.manialink('bob')
      assert [t[4:] for t in texts(page) if t.endswith('.')] == ['1.', '10.', '11.', '12.', '13.', '14.', '15.', '16.',
        '17.', '18.', '19.']
      await h.click('bob', action_of(page, '$fffMap 13'))
      assert await queue_uids(h) == ['uid13']
      assert h.manialink('bob') is None # closed after the wish

      await h.chat('bob', '/list')
      await h.click('bob', action_of(h.manialink('bob'), '$fffMap 4'))
      assert 'already have a map' in h.replies_to('bob')[-1] # same rules as /jukebox
      assert h.manialink('bob') is not None # stays open
      await h.click('bob', action_of(h.manialink('bob'), 'Close'))
      assert h.manialink('bob') is None

      await h.chat('bob', '/list nothing matches')
      assert 'No map matches' in h.replies_to('bob')[-1]
    #
  #
  run(scenario())
#


def test_jukebox_sets_next_map_and_follows_the_rules(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=PLUGINS) as h:
      await h.chat('bob', '/jukebox 4')
      assert next_file(h) == h.server.maps[3]['FileName']
      assert 'was added to the jukebox by' in h.announcements()[-1]
      await h.chat('bob', '/jb 5')
      assert 'already have a map' in h.replies_to('bob')[-1]
      await h.chat('carl', '/jb 4')
      assert 'already in the jukebox' in h.replies_to('carl')[-1]
      await h.chat('carl', '/jb 5')
      await h.chat('carl', '/jb 99')
      assert 'There is no map 99' in h.replies_to('carl')[-1]
      assert await queue_uids(h) == ['uid4', 'uid5']
      assert next_file(h) == h.server.maps[3]['FileName'] # still the first one

      await h.server.play_next() # map 4 starts
      await h.settle()
      assert await queue_uids(h) == ['uid5']
      assert next_file(h) == h.server.maps[4]['FileName']

      # map 4 was just played: players can't wish it, operators can
      await h.chat('bob', '/jb 4')
      assert 'played recently' in h.replies_to('bob')[-1]
      await h.controller.accounts.set_role('op', roles.OPERATOR)
      await h.chat('op', '/jb 4')
      await h.chat('op', '/jb 2') # operators have no limit
      assert await queue_uids(h) == ['uid5', 'uid4', 'uid2']

      await h.chat('carl', '/jukebox drop')
      assert await queue_uids(h) == ['uid4', 'uid2']
      assert next_file(h) == h.server.maps[3]['FileName']
      await h.chat('bob', '/jukebox drop 1')
      assert 'Usage' in h.replies_to('bob')[-1] # players can only drop their own
      await h.chat('op', '/jukebox drop 1')
      assert await queue_uids(h) == ['uid2']
      await h.chat('master', '/jukebox clear')
      assert await queue_uids(h) == []
    #
  #
  run(scenario())
#


def test_maps_the_server_refuses_are_not_queued(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=PLUGINS) as h:
      h.server.refuse.add(h.server.maps[2]['FileName'])
      await h.chat('bob', '/jb 3')
      assert 'does not fit the server settings: Wrong environment.' in h.replies_to('bob')[-1]
      assert await queue_uids(h) == []
    #
  #
  run(scenario())
#


def test_queue_survives_a_restart(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=PLUGINS) as h:
      await h.chat('bob', '/jb 3')
      server = h.server
    #
    async with Harness(tmp_path, plugins=PLUGINS, server=server) as h:
      assert await queue_uids(h) == ['uid3']
      assert next_file(h) == h.server.maps[2]['FileName']
    #
  #
  run(scenario())
#


def test_replay_vote_goes_first_in_the_jukebox(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=PLUGINS) as h:
      await h.chat('bob', '/jb 3')
      # the vote passed: the server sends the Echo of the vote (swapped parameters)
      await h.server.callback('TrackMania.Echo', 'replay', 'Replay this map')
      await h.settle()
      assert await queue_uids(h) == ['uid1', 'uid3'] # uid1 is the current map
      assert next_file(h) == h.server.maps[0]['FileName']
    #
  #
  run(scenario())
#


def test_temporary_maps_are_removed_after_they_were_played(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=PLUGINS) as h:
      jukebox = h.plugin('jukebox')
      from plugins.jukebox import Entry
      new = Entry('uid-Challenges\\TMX\\7.Challenge.Gbx', 'Challenges\\TMX\\7.Challenge.Gbx', 'TMX 7', source='TMX')
      assert await jukebox.add(new, roles.ADMIN, jukebox.no_reply, temporary=True)
      assert h.server.called('AddChallenge') == [('Challenges\\TMX\\7.Challenge.Gbx',)]
      await h.server.play_next() # the TMX map
      await h.settle()
      assert h.server.maps[h.server.current]['UId'] == new.uid
      await h.server.play_next() # something else: the TMX map is removed
      await h.settle()
      assert h.server.called('RemoveChallenge') == [('Challenges\\TMX\\7.Challenge.Gbx',)]
      assert new.uid not in h.controller.maps.by_uid

      # kept with /addthis
      other = Entry('uid-Challenges\\TMX\\8.Challenge.Gbx', 'Challenges\\TMX\\8.Challenge.Gbx', 'TMX 8', source='TMX')
      await jukebox.add(other, roles.ADMIN, jukebox.no_reply, temporary=True)
      await h.server.play_next()
      await h.settle()
      await h.chat('bob', '/addthis')
      assert 'You need to be admin' in h.replies_to('bob')[-1]
      await h.chat('master', '/addthis')
      assert 'stays on the server' in h.replies_to('master')[-1]
      await h.server.play_next()
      await h.settle()
      assert len(h.server.called('RemoveChallenge')) == 1
    #
  #
  run(scenario())
#


def test_xaseco_side_requests_and_state(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=PLUGINS) as h:
      def request(**data):
        # what the XAseco side sends: Echo('pyseco-shim|<json>', 'pyseco-shim'), arriving swapped
        return h.server.callback('TrackMania.Echo', 'pyseco-shim', 'pyseco-shim|' + json.dumps(data))
      #
      def last_state():
        first = [params[0] for params in h.server.called('Echo') if params[1] == 'pyseco'][-1]
        return json.loads(first[len('pyseco|'):])
      #
      await request(action='add', uid='uid3', filename=h.server.maps[2]['FileName'], login='eve', nickname='Eve')
      await h.settle()
      assert await queue_uids(h) == ['uid3']
      state = last_state()
      assert state['queue'][0] | {} == {'uid': 'uid3', 'FileName': h.server.maps[2]['FileName'], 'Name': '$f00Map 3',
        'Env': 'Stadium', 'Login': 'eve', 'Nick': 'Eve', 'source': 'Jukebox', 'tmx': False}

      await request(action='add', uid='uid4', filename=h.server.maps[3]['FileName'], login='eve', nickname='Eve')
      await h.settle()
      assert 'already have a map' in h.replies_to('eve')[-1] # the same rules apply
      assert [e['uid'] for e in last_state()['queue']] == ['uid3'] # XAseco side gets the real state back

      await request(action='drop', uid='uid3', login='mallory')
      await h.settle()
      assert await queue_uids(h) == ['uid3'] # not mallory's
      await request(action='drop', uid='uid3', login='eve')
      await h.settle()
      assert await queue_uids(h) == []

      count = len(h.server.called('Echo'))
      await request(action='hello')
      await h.settle()
      assert len(h.server.called('Echo')) == count + 1
    #
  #
  run(scenario())
#


def test_nextmap_and_history(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=PLUGINS) as h:
      await h.chat('bob', '/nextmap')
      assert h.replies_to('bob')[-1].endswith('Next map: $fffMap 2$z$s')
      await h.chat('bob', '/jb 4')
      await h.chat('bob', '/nextmap')
      assert 'Map 4' in h.replies_to('bob')[-1]
      await h.chat('bob', '/history')
      assert 'No maps were played yet' in h.replies_to('bob')[-1]
      await h.server.play_next()
      await h.server.play_next()
      await h.settle()
      await h.chat('bob', '/history')
      assert '1. $fffMap 4$z$s' in h.replies_to('bob')[-1]
    #
  #
  run(scenario())
#


def test_jukebox_with_the_memory_backend(tmp_path):
  # the controller and the plugins only use the storage interface
  async def scenario():
    async with Harness(tmp_path, '[storage]\nbackend = "memory"\n', plugins=PLUGINS) as h:
      await h.chat('bob', '/jb 3')
      await h.chat('master', '/setrole bob operator')
      await h.server.play_next() # map 3 (from the jukebox)
      await h.server.play_next() # map 4
      await h.settle()
      await h.chat('bob', '/history')
      assert '1. $fffMap 3$z$s' in h.replies_to('bob')[-1]
      assert not (tmp_path / 'data' / 'pyseco.db').exists()
    #
  #
  run(scenario())
#
