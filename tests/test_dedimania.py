import asyncio
import time

from conftest import Harness, texts
from fake_dedimania import FakeDedimania


def run(coro):
  return asyncio.run(coro)
#


def config(dedi, extra=''):
  return '[dedimania]\ncode = "secret"\nnation = "GER"\nurl = "' + dedi.url + '"\n' + extra
#


def widget_lines(page):
  t = texts(page)[1:]
  return [(t[i][4:], t[i + 1][4:], t[i + 2]) for i in range(0, len(t), 3)]
#


def test_records_come_and_new_ones_are_sent(tmp_path):
  async def scenario():
    dedi = FakeDedimania()
    dedi.records = [{'Login': 'wr', 'NickName': 'World Record', 'Best': 9000, 'Checks': [3000, 6000, 9000]},
      {'Login': 'second', 'NickName': 'Second', 'Best': 9500, 'Checks': [3100, 6300, 9500]}]
    await dedi.start()
    async with Harness(tmp_path, config(dedi), plugins=('dedimania',)) as h:
      await h.settle(0.5)
      auth = dedi.called('dedimania.Authenticate')[0][0]
      assert (auth['Login'], auth['Tool'], auth['Nation'], auth['Game']) == ('fakeserver', 'pyseco', 'GER', 'TMF')
      assert dedi.called('dedimania.ValidateAccount')
      challenge = dedi.called('dedimania.CurrentChallenge')[-1]
      assert challenge[:6] == ('uid1', '$f00Map 1', 'Stadium', 'author1', 'TMF', 1)

      await h.join('ann', 'Ann')
      await h.settle(0.3)
      arrive = dedi.called('dedimania.PlayerArrive')[-1]
      assert arrive[:4] == ('TMF', 'ann', 'Ann', 'GER')
      assert widget_lines(h.manialink('ann'))[:2] == [('1.', '0:09.00', 'World Record'), ('2.', '0:09.50', 'Second')]

      await h.drive('ann', [3000, 6100, 9200])
      assert 'Ann$z$s gained the $fff2nd$z$s Dedimania record: $fff0:09.20' in h.announcements()[-1]
      await h.drive('ann', [3000, 6100, 9300]) # slower: nothing
      await h.drive('ann', [3000, 6100, 9100])
      assert 'improved to the $fff2nd$z$s Dedimania record: $fff0:09.10$z$s ($fff-0.10$z$s)' in h.announcements()[-1]
      await h.server.callback('TrackMania.PlayerCheckpoint', 5, 'ann', 3000, 0, 0)
      await h.server.callback('TrackMania.PlayerFinish', 5, 'ann', 8000) # checkpoints don't match: ignored
      await h.settle()
      assert 'Dedimania' not in h.announcements()[-1] or '0:08.00' not in h.announcements()[-1]

      await h.server.play_next()
      await h.settle(0.5)
      times = dedi.called('dedimania.ChallengeRaceTimes')[-1]
      assert times[0] == 'uid1' and times[6] == 3 # 3 checkpoints
      assert times[8] == [{'Login': 'ann', 'Best': 9100, 'Checks': '3000,6100,9100'}]
      assert dedi.called('dedimania.CurrentChallenge')[-1][0] == 'uid2'
    #
    await dedi.stop()
  #
  run(scenario())
#


def test_read_only_and_wrong_code(tmp_path):
  async def scenario():
    dedi = FakeDedimania()
    await dedi.start()
    async with Harness(tmp_path, config(dedi, 'send = false\n'), plugins=('dedimania',)) as h:
      await h.join('ann', 'Ann')
      await h.drive('ann', [3000, 6100, 9200])
      await h.server.play_next()
      await h.settle(0.5)
      assert not dedi.called('dedimania.ChallengeRaceTimes')
    #
    dedi.code = 'other'
    dedi.calls = []
    async with Harness(tmp_path, config(dedi), plugins=('dedimania',)) as h:
      await h.settle(0.5)
      # one request (the login, refused); nothing after it
      assert [m for m, _ in dedi.calls] == ['dedimania.Authenticate', 'dedimania.ValidateAccount',
        'dedimania.WarningsAndTTR']
      assert not h.plugin('dedimania').ready and h.plugin('dedimania').failed_at is not None
    #
    await dedi.stop()
  #
  run(scenario())
#


def test_an_unreachable_dedimania_holds_up_nothing(tmp_path):
  async def scenario():
    async def never_answer(reader, writer):
      await asyncio.sleep(10)
    #
    silent = await asyncio.start_server(never_answer, '127.0.0.1', 0)
    url = 'url = "http://127.0.0.1:' + str(silent.sockets[0].getsockname()[1]) + '/Dedimania"\ntimeout = 1.5\n'
    async with Harness(tmp_path, '[dedimania]\ncode = "x"\n' + url, plugins=('dedimania',)) as h:
      start = time.monotonic()
      await h.chat('bob', '/dedirecs')
      assert h.manialink('bob') is not None and time.monotonic() - start < 1 # while Dedimania doesn't answer
      await h.settle(1.6)
      assert not h.plugin('dedimania').ready and h.plugin('dedimania').failed_at is not None # gave up, retries later
    #
    silent.close()
  #
  run(scenario())
#
