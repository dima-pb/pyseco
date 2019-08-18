import datetime
import os

import config


LOG_ALL = 0
LOG_VERBOSE = 1
LOG_DEBUG = 2
LOG_INFO = 3
LOG_WARNING = 4
LOG_ERROR = 5
LOG_FATAL = 6
LOG_DISABLED = 7


class Logging:

  def __init__(self, path, level = LOG_INFO):
    self.path = path
    self.level = level
    self.level_names = ['ALL', 'VERBOSE', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'FATAL', 'DISABLED']
  #
  
  def message(self, content, level = LOG_INFO):
    if level < self.level:
      return
    #
    
    today = datetime.datetime.today()
    filename = str(today.year) + '.' + str(today.month) + '.' + str(today.day) + '.log'
    filepath = os.path.join(self.path, filename)
    
    time = datetime.datetime.now()
    msg = '| ' + str(time) + ' | ' + self.level_names[level].rjust(8) + ' | ' + content + os.linesep
    print(msg)
    
    f = open(filepath, 'a')
    f.write(msg)
    f.close()
  #
#

