import plugins.discord as discord
import plugins.echo as echo
import plugins.custom_votes as custom_votes


class Plugins:
  def __init__(self, controller):
    self.plugins = []
    
    #self.plugins.append(discord.Discord(controller))
    #self.plugins.append(echo.Echo(controller))
    self.plugins.append(custom_votes.CustomVote(controller))
  #
#