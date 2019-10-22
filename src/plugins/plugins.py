import plugins.discord as discord
import plugins.echo as echo
import plugins.custom_votes as custom_votes
import plugins.ad as ad


class Plugins:
  def __init__(self, controller):
    self.plugins = []
    
    #self.plugins.append(echo.Echo(controller))
    #self.plugins.append(custom_votes.CustomVote(controller))
    self.plugins.append(ad.Ad(controller))
    self.plugins.append(discord.Discord(controller))
  #
#