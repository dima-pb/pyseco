import plugins.discord as discord
import plugins.echo as echo


class Plugins:
  def __init__(self, controller):
    self.plugins = []
    
    self.plugins.append(discord.Discord(controller))
    #self.plugins.append(echo.Echo(controller))
  #
#