import asyncio

from conftest import Harness, action_of, texts


def run(coro):
  return asyncio.run(coro)
#


def widget_lines(page):
  # (rank, time, name) of every line of the records widget
  t = texts(page)[1:]
  return [(t[i][4:], t[i + 1][4:], t[i + 2]) for i in range(0, len(t), 3)]
#


def test_records_are_kept_with_checkpoints_and_told(tmp_path):
  async def scenario():
    async with Harness(tmp_path, '[local_records]\nannounce = 2\n', plugins=('local_records',)) as h:
      for login in ('ann', 'bob', 'cid'):
        await h.join(login, login.capitalize())
      #
      await h.drive('ann', [3000, 6100, 9080])
      assert h.announcements()[-1].endswith('$fffAnn$z$s drove the $fff1st$z$s local record: $fff0:09.08$z$s')
      await h.drive('bob', [2900, 6000, 9050])
      assert 'Bob$z$s drove the $fff1st' in h.announcements()[-1]
      await h.drive('ann', [3000, 6100, 9100]) # slower: nothing happens
      await h.drive('cid', [3100, 6200, 9080]) # equal to ann, but later: 3rd, not announced
      assert 'Cid' not in h.announcements()[-1]
      assert h.replies_to('cid')[-1].endswith('Your best time: $fff0:09.08$z$s, the 3rd local record.')
      await h.drive('ann', [2900, 5900, 9000])
      assert 'Ann$z$s improved to the $fff1st$z$s local record: $fff0:09.00$z$s ($fff-0.08$z$s)' in h.announcements()[-1]

      record = await h.controller.storage.records.best('uid1', 'ann')
      assert (record.time, record.checkpoints) == (9000, [2900, 5900, 9000])
      assert widget_lines(h.manialink('cid')) == [('1.', '0:09.00', 'Ann'), ('2.', '0:09.05', 'Bob'), ('3.', '0:09.08', 'Cid')]

      # restarting (finish with time 0) or giving up stores nothing
      await h.server.callback('TrackMania.PlayerCheckpoint', 5, 'cid', 1000, 0, 0)
      await h.server.callback('TrackMania.PlayerFinish', 5, 'cid', 0)
      await h.settle()
      assert (await h.controller.storage.records.best('uid1', 'cid')).time == 9080
    #
  #
  run(scenario())
#


def test_widget_shows_top_the_one_to_beat_own_and_last(tmp_path):
  async def scenario():
    async with Harness(tmp_path, '[local_records]\ntop = 5\n', plugins=('local_records',)) as h:
      for n in range(1, 11):
        await h.join('p' + str(n))
        await h.drive('p' + str(n), [9000 + n * 10])
      #
      await h.join('new')
      lines = widget_lines(h.manialink('new'))
      assert [l[0] for l in lines] == ['1.', '2.', '3.', '4.', '5.', '10.', '--.'] # no record yet: the own line
      assert lines[-2] == ('10.', '0:09.10', 'p10') and lines[-1] == ('--.', '-:--.--', 'new')
      assert [l[0] for l in widget_lines(h.manialink('p8'))] == ['1.', '2.', '3.', '4.', '5.', '7.', '8.', '10.']
      assert [l[0] for l in widget_lines(h.manialink('p10'))] == ['1.', '2.', '3.', '4.', '5.', '9.', '10.']
      assert [l[0] for l in widget_lines(h.manialink('p6'))] == ['1.', '2.', '3.', '4.', '5.', '6.', '10.']
      assert [l[0] for l in widget_lines(h.manialink('p2'))] == ['1.', '2.', '3.', '4.', '5.', '10.']
    #
  #
  run(scenario())
#


def test_records_window_and_checkpoints(tmp_path):
  async def scenario():
    async with Harness(tmp_path, plugins=('local_records',)) as h:
      await h.join('ann', 'Ann')
      await h.drive('ann', [3000, 6100, 9080])
      await h.click('ann', h.controller.plugins.get('local_records').widget.action)
      page = h.manialink('ann')
      assert '$fffLocal Records on Map 1' in texts(page) and '$ff00:09.08' in texts(page)
      await h.click('ann', action_of(page, '$fffAnn'))
      assert texts(h.manialink('ann')) == ['$fff1st Ann 0:09.08', '$dddCP 1', '$fff0:03.00', '$ddd+0:03.00', '',
        '$dddCP 2', '$fff0:06.10', '$ddd+0:03.10', '', '$dddFinish', '$fff0:09.08', '$ddd+0:02.98', '']

      # somebody else's record: compared with the own checkpoints
      await h.join('bob', 'Bob')
      await h.drive('bob', [2900, 6200, 9050])
      await h.chat('ann', '/records')
      await h.click('ann', action_of(h.manialink('ann'), '$fffBob'))
      shown = texts(h.manialink('ann'))
      assert shown[0] == '$fff1st Bob 0:09.05'
      assert shown[1:5] == ['', '$999Bob', '$999you', '$999you - them']
      assert shown[5:9] == ['$dddCP 1', '$fff0:02.90', '$fff0:03.00', '$f66+0.10']
      assert shown[9:13] == ['$dddCP 2', '$fff0:06.20', '$fff0:06.10', '$6f6-0.10']
      assert shown[-1] == '$f66+0.03'

      # the whole widget opens the records
      widget = h.manialink('ann', h.controller.plugins.get('local_records').widget.id)
      opens = str(h.controller.plugins.get('local_records').widget.action)
      assert widget.find('frame').find('quad').get('action') == opens # the background

      # a new map: its own records
      await h.server.play_next()
      await h.settle()
      assert widget_lines(h.manialink('ann')) == [('--.', '-:--.--', 'Ann')]
    #
  #
  run(scenario())
#
