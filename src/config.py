import os
import tomllib


LOG_LEVELS = {'all': 0, 'verbose': 1, 'debug': 2, 'info': 3, 'warning': 4, 'error': 5, 'fatal': 6, 'disabled': 7}


class ConfigError(Exception):
  pass
#


class Config:
  # All settings in one TOML file (see pyseco.toml.example):
  #   [server]      connection to the dedicated server
  #   [controller]  masteradmins, plugins, data directory, logging
  #   [<plugin>]    one section per plugin, read by the plugin with section('<plugin>')
  # Relative paths are relative to the directory of the settings file.

  def __init__(self, filename):
    self.filename = filename
    self.base_dir = os.path.dirname(os.path.abspath(filename))
    try:
      with open(filename, 'rb') as f:
        self.data = tomllib.load(f)
      #
    except FileNotFoundError:
      raise ConfigError('Settings file ' + filename + ' not found (see pyseco.toml.example)') from None
    except tomllib.TOMLDecodeError as exc:
      raise ConfigError('Settings file ' + filename + ' is not valid TOML: ' + str(exc)) from None
    #

    server = self.section('server')
    self.url = server.get('host', '127.0.0.1')
    self.port = int(server.get('port', 5000))
    self.username_superadmin = server.get('login', 'SuperAdmin')
    self.password_superadmin = server.get('password', 'SuperAdmin')

    controller = self.section('controller')
    self.masteradmins = [login for login in controller.get('masteradmins', []) if login]
    self.plugins = list(controller.get('plugins', []))
    self.data_dir = self.path(controller.get('data_dir', 'data'))
    level = str(controller.get('log_level', 'info')).lower()
    if level not in LOG_LEVELS:
      raise ConfigError('log_level must be one of ' + ', '.join(LOG_LEVELS))
    #
    self.log_level = LOG_LEVELS[level]
    self.log_path = os.path.join(self.data_dir, 'logs')
    self.database = os.path.join(self.data_dir, 'pyseco.db')
  #

  def section(self, name):
    value = self.data.get(name, {})
    if not isinstance(value, dict):
      raise ConfigError('[' + name + '] in ' + self.filename + ' must be a section')
    #
    return value
  #

  def path(self, value):
    return value if os.path.isabs(value) else os.path.join(self.base_dir, value)
  #
#
