import importlib
import traceback

from core import log


# plugin name (as used in pyseco.toml) -> module, class
AVAILABLE = {
  'admin_panel': ('plugins.admin_panel', 'AdminPanel'),
  'ad': ('plugins.ad', 'Ad'),
  'custom_votes': ('plugins.custom_votes', 'CustomVote'),
  'dedimania': ('plugins.dedimania', 'Dedimania'),
  'discord': ('plugins.discord', 'Discord'),
  'flexitime': ('plugins.flexitime', 'Flexitime'),
  'jukebox': ('plugins.jukebox', 'Jukebox'),
  'local_records': ('plugins.local_records', 'LocalRecords'),
  'tmx': ('plugins.tmx', 'Tmx'),
  'welcome': ('plugins.welcome', 'Welcome'),
}


class Plugins:
  def __init__(self, controller, names):
    self.controller = controller
    self.names = names
    self.plugins = []
    self.by_name = {}
  #
  
  def get(self, name):
    # a started plugin by its name, or None
    return self.by_name.get(name)
  #

  async def start(self):
    logger = self.controller.logger
    for name in self.names:
      if name not in AVAILABLE:
        logger.message('Unknown plugin ' + name, log.LOG_ERROR)
        continue
      #
      module_name, class_name = AVAILABLE[name]
      # a broken plugin (missing library, bad settings, ...) is skipped instead of stopping the controller
      try:
        module = importlib.import_module(module_name)
        plugin = getattr(module, class_name)(self.controller)
        await plugin.start()
      except Exception:
        logger.message('Plugin ' + name + ' could not be started:\n' + traceback.format_exc(), log.LOG_ERROR)
        continue
      #
      self.plugins.append(plugin)
      self.by_name[name] = plugin
      logger.message('Plugin ' + name + ' started', log.LOG_INFO)
    #
  #

  async def stop(self):
    # stops every plugin once
    plugins, self.plugins = self.plugins, []
    for plugin in plugins:
      try:
        await plugin.stop()
      except Exception:
        self.controller.logger.message('Plugin stop failed:\n' + traceback.format_exc(), log.LOG_ERROR)
      #
    #
  #
#
