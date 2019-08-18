from plugins.plugin import Plugin

class Echo(Plugin):

  def __init__(self, controller):
    super().__init__(controller)
    self.controller.register_event('TrackMania.PlayerChat', self.echo)
  #

  def echo(self, params):
    print(str(params))
    if params[0] == 0: # don't react to server-own messages
      return
    #
    
    self.controller.chat_send(params[1] + ' wrote ' + params[2])
  #
#

