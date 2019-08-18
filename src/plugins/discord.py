import asyncio
import discord
import threading
import queue
import os

from plugins.plugin import Plugin
import utilities

class Discord(Plugin):

  def __init__(self, controller):
    super().__init__(controller)
    self.read_settings()
    
    self.client = DiscordClient(self.channel_id)
    asyncio.get_child_watcher()
    self.loop = asyncio.get_event_loop()
    self.loop.create_task(self.start_discord_client())
    
    thread = threading.Thread(target = self.run_loop)
    thread.daemon = True
    thread.start()
    
    self.controller.register_event('TrackMania.PlayerChat', self.post_to_dc)
    self.controller.register_event('tick', self.tick)
  #
  
  async def start_discord_client(self):
    await self.client.start(self.bot_token)
  #
  
  def run_loop(self):
    self.loop.run_forever()
  #
  
  def read_settings(self):
    cfg = open(os.path.join('plugins', 'discord.ini'), 'r')
    for line in cfg:
      kv = line.split('=')
      if len(kv) != 2:
        continue
      #
      if kv[0] == 'bot_token':
        self.bot_token = kv[1].strip()
      if kv[0] == 'channel_id':
        self.channel_id = int(kv[1].strip())
      #
    #
    if self.bot_token is None or self.channel_id is None:
      raise Exception('Invalid or missing settings file for discord plugin. [discord.ini]')
    #
  #

  def post_to_dc(self, params):
    if params[0] == 0:
      return
    #
    
    login = params[1]
    player = self.controller.get_player_by_login(login)
    nickname_clean = utilities.strip_colors(player.nickname)
    if nickname_clean is None:
      nickname_clean = ''
    #
    
    msg = nickname_clean + '[' + login + '] : ' + params[2]
    print(msg)
    
    if self.client.channel is not None:
      asyncio.run_coroutine_threadsafe(self.client.channel.send(msg), self.loop)
    
  #
  
  def tick(self, params):
    while not self.client.messages.empty():
      msg = self.client.messages.get()
      self.controller.chat_send_server_message(msg[0] + '@discord: $fe1' + msg[1])
    #
  #
#


class DiscordClient(discord.Client):

  def __init__(self, channel_id):
    super().__init__()
    self.channel_id = channel_id
    self.channel = None
    self.messages = queue.Queue()
  #

  async def on_ready(self):
    self.channel = self.get_channel(self.channel_id)
    self.messages.put(('Bot', 'I\'m ready for action!',))
  #

  async def on_message(self, message):
    if message.author == self.user or message.channel != self.channel:
      return
    #

    self.messages.put((message.author.display_name, message.content,))
  #
#