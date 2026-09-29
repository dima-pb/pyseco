import asyncio
import types

import accounts
from conftest import Harness

DISCORD_CONFIG = '[discord]\ntoken = "test"\nchannel_id = 123\ninvite = "discord.gg/test"\n'


def message(author_id, name, content, channel_id=123):
  author = types.SimpleNamespace(id=author_id, display_name=name, mention='<@' + str(author_id) + '>')
  return types.SimpleNamespace(author=author, content=content, channel=types.SimpleNamespace(id=channel_id))
#


class FakeChannel:
  id, name = 123, 'tm-chat'

  def __init__(self):
    self.sent = []
  #

  async def send(self, text):
    self.sent.append(text)
  #
#


async def discord_plugin(h):
  # the plugin without logging in to discord: messages go to a fake channel
  import plugins.discord as dc
  plugin = dc.Discord(h.controller)
  plugin.sender_task = asyncio.create_task(plugin.sender())
  plugin.channel = FakeChannel()
  plugin.ready.set()
  return plugin
#


async def say(plugin, author_id, text, channel_id=123):
  await plugin.on_message(message(author_id, 'User' + str(author_id), text, channel_id))
  await asyncio.sleep(0.05)
  sent = plugin.channel.sent[:]
  plugin.channel.sent.clear()
  return '\n'.join(sent)
#


def test_discord_commands_use_linked_roles(tmp_path):
  async def scenario():
    async with Harness(tmp_path, DISCORD_CONFIG) as h:
      plugin = await discord_plugin(h)
      assert 'Not linked' in await say(plugin, 42, '!whoami')
      assert 'You need to be admin' in await say(plugin, 42, '!skip')
      assert 'Unknown or expired code' in await say(plugin, 42, '!link 123')
      assert 'Usage: !link <code>' in await say(plugin, 42, '!link')

      # the masteradmin links the discord account in game and on discord
      await h.chat('master', '/link')
      code = h.replies_to('master')[-1].split('!link ')[1].split('$')[0]
      assert 'Linked to master (masteradmin)' in await say(plugin, 42, '!link ' + code)
      assert 'Linked to master' in await say(plugin, 42, '!whoami')
      await say(plugin, 42, '!skip')
      assert h.server.called('NextChallenge')

      # commands for the game only are unknown on discord, discord only commands too in game
      assert 'Unknown command' in await say(plugin, 42, '!pyseco')
      help_text = await say(plugin, 42, '!help')
      assert '!setrole' in help_text and '!players' in help_text and '/link' not in help_text.split('\n')[0]

      assert 'Link removed' in await say(plugin, 42, '!unlink')
      assert 'You need to be admin' in await say(plugin, 42, '!skip')
      await plugin.stop()
    #
  #
  asyncio.run(scenario())
#


def test_discord_chat_goes_to_game(tmp_path):
  async def scenario():
    async with Harness(tmp_path, DISCORD_CONFIG) as h:
      plugin = await discord_plugin(h)
      await say(plugin, 7, 'hello $f00game')
      sent = h.server.called('ChatSendServerMessage')[-1][0]
      assert sent.startswith('[User7@$l[discord.gg/test]discord$l]') and sent.endswith('hello $f00game')
      await say(plugin, 7, 'other channel', channel_id=999) # ignored
      assert len(h.server.called('ChatSendServerMessage')) == 1
      await plugin.stop()
    #
  #
  asyncio.run(scenario())
#
