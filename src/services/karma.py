from core import events


def percent(plus, minus):
  # share of good votes, None without votes
  return round(100 * plus / (plus + minus)) if plus + minus else None
#


def text(plus, minus):
  # e.g. '$0f0+6 $f44-2' (TM colors), '' without votes
  return '$0f0+' + str(plus) + ' $f44-' + str(minus) if plus + minus else ''
#


class Karma:
  # How players rate maps: one vote per player and map, ++ (good) or -- (bad); voting again replaces the vote.
  # The karma plugin is how players vote; others (e.g. the map list) show the counts.

  def __init__(self, controller):
    self.controller = controller
    self.store = controller.storage.karma
  #

  async def vote(self, uid, login, value):
    # value: 1 or -1; raises events.KARMA_CHANGED
    await self.store.vote(uid, login, 1 if value > 0 else -1)
    await self.controller.events.emit(events.KARMA_CHANGED, uid)
  #

  async def unvote(self, uid, login):
    # takes the vote back, the map is unrated by the player again; raises events.KARMA_CHANGED
    if await self.store.unvote(uid, login):
      await self.controller.events.emit(events.KARMA_CHANGED, uid)
    #
  #

  async def votes(self, uid):
    # {login: 1 or -1}
    return await self.store.votes(uid)
  #

  async def counts(self, uids):
    # {uid: (plus, minus)} of the maps with votes
    return await self.store.counts(uids)
  #
#
