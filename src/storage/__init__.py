# Where pyseco keeps its data. See storage/interfaces.py for what is kept; backends implement it.
#
# [storage] in pyseco.toml:
#   backend = "sqlite"   one file, <data_dir>/pyseco.db (default)
#   backend = "memory"   nothing is kept when pyseco stops (tests)


from core.config import STORAGE_BACKENDS as BACKENDS


def create(config):
  backend = config.section('storage').get('backend', 'sqlite')
  if backend == 'sqlite':
    from storage.sqlite import SqliteStorage
    return SqliteStorage(config.database)
  #
  if backend == 'memory':
    from storage.memory import MemoryStorage
    return MemoryStorage()
  #
  raise ValueError('Unknown storage backend "' + str(backend) + '", available: ' + ', '.join(BACKENDS))
#
