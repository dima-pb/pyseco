from plugins.plugin import Plugin

class Ad(Plugin):

  def __init__(self, controller):
    super().__init__(controller)
    self.controller.register_event('PlayerConnectComplete', self.show_ad)
  #

  def show_ad(self, login):
    xml = '''
      <manialink id="7998">
        <quad posn="-67 -15 0" size="0.21 0.14" image="http://217.160.14.228/mods/wlogo.png" url="discord.gg/JPjDafk" />
      </manialink>'''
    duration = 0
    hide_on_click = False
    
    self.controller.send_display_manialink_page_to_login(login, xml, duration, hide_on_click)
  #
#

