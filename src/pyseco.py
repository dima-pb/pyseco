import argparse
import asyncio
import signal
import sys
import traceback

from core import config, log
from core.controller import AuthenticationError, Controller


async def main():
  parser = argparse.ArgumentParser(description='TrackMania Forever server controller')
  parser.add_argument('--config', default='pyseco.toml',
    help='settings file (default: pyseco.toml); relative paths in it are relative to its directory')
  args = parser.parse_args()

  try:
    cfg = config.Config(args.config)
  except config.ConfigError as exc:
    print(exc, file=sys.stderr)
    return 1
  #
  logger = log.Logging(cfg.log_path, cfg.log_level)

  controller = Controller(cfg, logger)
  # docker and systemd stop programs with SIGTERM: shut down cleanly (plugins, discord logout)
  asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(controller.stop()))
  try:
    await controller.run()
  except AuthenticationError as exc:
    logger.message(str(exc), log.LOG_FATAL)
    return 1
  except Exception as exc:
    logger.message(str(exc), log.LOG_ERROR)
    logger.message(traceback.format_exc(), log.LOG_ERROR)
    return 1
  #
  return 0
#


if __name__ == '__main__':
  try:
    sys.exit(asyncio.run(main()))
  except KeyboardInterrupt:
    pass
  #
#
