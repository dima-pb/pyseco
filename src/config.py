

class Config:

  def __init__(self, filename):
    self.filename = filename
    self.set_defaults()
    self.read_config()
  #
  
  def set_defaults(self):
    self.url = '127.0.0.1'
    self.port = 5000
    self.username_superadmin = 'SuperAdmin'
    self.password_superadmin = 'SuperAdmin'
    self.username_admin = 'Admin'
    self.password_admin = 'Admin'
    self.username_user = 'User'
    self.password_user = 'User'
    self.log_path = 'Logs'
    self.log_level = 3
  #
  
  def read_config(self):
    f = open(self.filename, 'r')
    for line in f:
      kv = line.split('=')
      if len(kv) != 2:
        continue
      #
      if kv[0] == 'url':
        self.url = kv[1].strip()
      elif kv[0] == 'port':
        self.port = int(kv[1].strip())
      elif kv[0] == 'username_superadmin':
        self.username_superadmin = kv[1].strip()
      elif kv[0] == 'password_superadmin':
        self.password_superadmin = kv[1].strip()
      elif kv[0] == 'username_admin':
        self.username_admin = kv[1].strip()
      elif kv[0] == 'password_admin':
        self.password_admin = kv[1].strip()
      elif kv[0] == 'username_user':
        self.username_user = kv[1].strip()
      elif kv[0] == 'password_user':
        self.password_user = kv[1].strip()
      elif kv[0] == 'log_path':
        self.log_path = kv[1].strip()
      elif kv[0] == 'log_level':
        self.log_level = int(kv[1].strip())
      #
    #
    f.close()
  #
  
  def dump(self):
    print(self.url)
    print(self.port)
    print(self.username_superadmin)
    print(self.password_superadmin)
    print(self.username_admin)
    print(self.password_admin)
    print(self.username_user)
    print(self.password_user)
    print(self.log_path)
    print(self.log_level)
  #
#
