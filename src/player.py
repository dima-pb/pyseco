import utilities

class Player:

  def __init__(self, login, is_spec = False):
    self.login = login
    self.nickname = self.login
    
    self.id = None
    self.team_id = None
    self.is_spec = is_spec
    self.ladder_rank = None
    self.flags = None # ??
  #
#