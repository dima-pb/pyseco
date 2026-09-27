class Plugin:
  # Register event handlers in __init__ (they must be async functions).
  # Anything that needs to talk to the server or the network belongs into start().

  def __init__(self, controller):
    self.controller = controller
  #

  async def start(self):
    pass
  #

  async def stop(self):
    pass
  #
#
