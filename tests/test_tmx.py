import asyncio

from core import roles
from conftest import Harness, texts
from fake_tmx import FakeTmx, track


def run(coro):
  return asyncio.run(coro)
#


def config(tmx):
  return '[tmx]\nurl = "' + tmx.url + '"\n'
#


def test_infos_and_widget_of_the_current_map(tmp_path):
  async def scenario():
    tmx = FakeTmx()
    tmx.tracks[100] = track(100, 'On TMX', 'uid1')
    tmx.replays[100] = [{'ReplayId': 500 + i, 'ReplayTime': 18670 + i * 10, 'User': {'Name': 'Driver' + str(i)},
      'ReplayAt': '2023-02-14'} for i in range(8)]
    tmx.replays[100].insert(1, {'ReplayTime': 18675, 'User': {'Name': 'Driver0'}}) # a second, slower replay: left out
    await tmx.start()
    async with Harness(tmp_path, config(tmx), plugins=('tmx',)) as h:
      await h.join('ann', 'Ann')
      await h.settle(0.5)
      widget = texts(h.manialink('ann', h.plugin('tmx').widget.id))
      assert widget[0] == '$fffTMX' and len(widget) == 1 + 5 * 3 # the top 5, nothing personal
      assert widget[1:4] == ['$ddd1.', '$ff00:18.67', 'Driver0'] and widget[6] == 'Driver1'
      urls = [q.get('url') for q in h.manialink('ann', h.plugin('tmx').widget.id).iter('quad') if q.get('url')]
      assert urls == ['tmnf.exchange/recordgbx/' + str(500 + i) for i in range(5)] # a click downloads the replay
      await h.click('ann', h.plugin('tmx').widget.action)
      assert '$l[tmnf.exchange/recordgbx/500]$fffDriver0$l' in texts(h.manialink('ann')) # TM adds http://

      await h.chat('ann', '/tmxinfo')
      shown = texts(h.manialink('ann'))
      assert shown[0] == '$fffTMX: On TMX'
      assert ['$dddAuthor', 'author'] == shown[3:5] and '$dddTags' in shown and 'Race, LOL' in shown
      assert '0:18.67 by nickie.' in shown
      assert '$l[tmnf.exchange/trackshow/100]tmnf.exchange/trackshow/100$l' in shown

      await h.server.play_next() # uid2 is not on TMX
      await h.settle(0.5)
      assert h.manialink('ann', h.plugin('tmx').widget.id) is None
      await h.chat('ann', '/tmxinfo')
      assert 'not on TMX' in h.replies_to('ann')[-1]
    #
    await tmx.stop()
  #
  run(scenario())
#


def test_admins_add_maps_by_id(tmp_path):
  async def scenario():
    tmx = FakeTmx()
    tmx.tracks[200] = track(200, 'Nice Map', 'tmx-uid-200')
    tmx.tracks[201] = track(201, 'Unlimited', 'tmx-uid-201', unlimiter=7)
    tmx.tracks[202] = track(202, 'Envmix', 'tmx-uid-202', car=3)
    tmx.tracks[203] = track(203, 'Map 3 on TMX', 'uid3') # already on the server
    await tmx.start()
    async with Harness(tmp_path, config(tmx), plugins=('tmx',)) as h:
      await h.controller.accounts.set_role('adm', roles.ADMIN)
      await h.chat('bob', '/add 200')
      assert 'You need to be admin' in h.replies_to('bob')[-1]

      await h.chat('adm', '/add 200 201 202 999 203')
      await h.settle(1)
      assert h.server.files == {'Challenges\\TMX\\200.Challenge.Gbx': b'GBX:tmx-uid-200'} # only the good one
      assert h.server.called('AddChallenge') == [('Challenges\\TMX\\200.Challenge.Gbx',)]
      replies = h.replies_to('adm')
      assert any('Unlimited (201) can\'t be added: it needs TMUnlimiter.' in r for r in replies)
      assert any('Envmix (202) can\'t be added: it is an environment mix.' in r for r in replies)
      assert any('There is no map 999 on TMX.' in r for r in replies)
      queue = h.controller.playlist.queue
      assert [(e.uid, e.source) for e in queue] == [('tmx-uid-200', 'TMX'), ('uid3', 'TMX')]
      assert h.controller.playlist.temporary == {'tmx-uid-200': 'Challenges\\TMX\\200.Challenge.Gbx'} # not uid3
      assert 'added $fffNice Map$z$s from TMX (200).' in h.announcements()[-2]
    #
    await tmx.stop()
  #
  run(scenario())
#


def test_random_maps_never_need_unlimiter(tmp_path):
  async def scenario():
    tmx = FakeTmx()
    tmx.tracks[300] = track(300, 'Sneaky Unlimiter', 'u300', unlimiter=7)
    tmx.tracks[301] = track(301, 'Random One', 'u301')
    tmx.tracks[302] = track(302, 'Stunt Map', 'u302', primary=1)
    tmx.tracks[303] = track(303, 'Random Two', 'u303')
    tmx.random = [300, 301, 302, 303]
    await tmx.start()
    async with Harness(tmp_path, config(tmx), plugins=('tmx',)) as h:
      await h.chat('master', '/rtmx 11')
      assert 'Usage' in h.replies_to('master')[-1]
      await h.chat('master', '/rtmx 2')
      await h.settle(1)
      assert [e.uid for e in h.controller.playlist.queue] == ['u301', 'u303']
      random_requests = [r for r in tmx.requests if r.startswith('/trackrandom')]
      assert all('inunlimiter=0' in r and 'inenvmix=0' in r and 'primarytype=0' in r for r in random_requests)

      await h.chat('master', '/rtmx') # TMX finds nothing more
      await h.settle(0.5)
      assert 'no random track found' in h.replies_to('master')[-1]
    #
    await tmx.stop()
  #
  run(scenario())
#
