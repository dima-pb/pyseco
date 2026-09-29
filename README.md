# pyseco
An attempt to create a poor-mans aseco for TMF in python


A controller for TMF Servers, written in python (asyncio).
Supports rpc calls (though most are yet to be defined) and callbacks from the server.

Supports plugins (I shamelessly stole the architecture for those from (x)aseco).
Which plugins are loaded is set with `plugins=` in `src/pyseco.cfg`:
  - `discord`: A discord bot that synchronises chat of a Trackmania server with a discord channel-chat.
  - `custom_votes`: A custom votes plugin that uses the native TMF voting engine. Currently only the usual replay and skip votes implemented,
    but more can very easily be added
  - `ad`: shows a clickable logo to every player that connects
  - `echo`: example plugin, repeats the chat
  - `jukebox`: players wish the next maps (`/list`, `/jukebox <number>`, `/nextmap`, `/history`); temporary
    (TMX) maps are removed after they were played unless an admin keeps them with `/addthis`. Replaces XAseco's
    jukebox: with XAseco running, its `plugin.rasp_jukebox.php` is replaced by the bridge from tmf-docker
    (`xaseco/addons`), so Records-Eyepiece's track list wishes maps through pyseco

## Setup
Requires Python 3.11 or newer.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp src/pyseco.toml.example src/pyseco.toml   # fill in: [server] connection, masteradmins, plugins
```

All settings are in `pyseco.toml`, one section per plugin. The discord bot needs the
**Message Content Intent** (Discord developer portal -> your app -> Bot).

Start with `src/pyseco.sh` (runs in the background, output in `src/pyseco.log`)
or in the foreground with `cd src && ../.venv/bin/python pyseco.py`.
`--config FILE` uses another settings file, e.g. to run one instance per server.
SIGTERM (docker, systemd) stops the controller cleanly.

## Data
Everything pyseco stores is in one SQLite database, `<data_dir>/pyseco.db` (players, roles, discord links, ...),
logs are in `<data_dir>/logs`. Back up the database with `sqlite3 pyseco.db ".backup copy.db"` or while pyseco is stopped.

## Roles and commands
Roles: player, operator, admin, masteradmin. Masteradmins are set in `pyseco.toml`, the others in game
with `/setrole <login> <player|operator|admin>`. `/pyseco` lists the commands you can use.

Discord commands (`!name`) use the role of the TM login the discord account is linked to:
type `/link` in game, then `!link <code>` in the discord channel. `!help` lists them.

## Writing plugins
Derive from `plugins.plugin.Plugin` and add the plugin to `AVAILABLE` in `src/plugins/plugins.py`. In `__init__`:
- settings: `controller.settings('<plugin>')`, the plugin's section of `pyseco.toml` as dict
- events: `controller.register_event(name, handler)`
- commands: `controller.commands.register(name, handler, role=accounts.ADMIN, help=..., usage=...,
  sources=(commands.GAME, commands.DISCORD))`; the handler gets a `commands.Context` (`ctx.login`, `ctx.args`,
  `await ctx.reply(text)`), raise `commands.UsageError` for wrong arguments
- tables: `await controller.db.migrate('<plugin>', [sql_v1, sql_v2, ...])` in `start()`; never change a
  released script, append a new one

Handlers are `async` functions; server requests are awaited, e.g. `await self.controller.call('GetChallengeList', 100, 0)`.
Never block in a handler (no `time.sleep`, no synchronous network calls): everything shares one event loop.

Events: all server callbacks (`TrackMania.PlayerChat`, ...) plus `PlayerConnectComplete` (login),
`PlayerDisconnectComplete` (player object) and `second_passed`.

## Tests
```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```
The tests run the controller against `tests/fake_server.py`, a stand-in for the dedicated server's XML-RPC interface.
