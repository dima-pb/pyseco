# pyseco
An attempt to create a poor-mans aseco for TMF in python


A controller for TMF Servers, written in python (asyncio).
Supports rpc calls (though most are yet to be defined) and callbacks from the server.

Supports plugins (I shamelessly stole the architecture for those from (x)aseco).
Which plugins are loaded is set with `plugins = [...]` in `src/pyseco.toml`:
  - `discord`: A discord bot that synchronises chat of a Trackmania server with a discord channel-chat, posts new
    local and Dedimania records, and runs commands (`!name`); a command that only tells the game answers "done".
    With an invite link, a small button in game opens it
  - `custom_votes`: A custom votes plugin that uses the native TMF voting engine. Currently only the usual replay and skip votes implemented,
    but more can very easily be added
  - `welcome`: greets players when they join, tells everybody who comes and goes
  - `flexitime`: the time limit of a map, kept by pyseco with a clock on screen; admins change it while the map
    is played (`/timeleft 30`, `/timeleft +10`, `/timeleft pause`, or a click on the clock to pause / resume)
  - `dedimania`: the Dedimania world records (dedimania.net) in a widget like the local records, `/dedirecs`; new
    records are sent when the map ends. Needs the server's Dedimania community code in `[dedimania]`
  - `local_records`: the best time of every player on every map, with the checkpoints of the run; a widget with
    the top 3 and the records around your own, `/records` (a click on a record shows its checkpoints)
  - `tmx`: maps from TMNF-X — admins add them by id (`/add <id>`) or at random (`/rtmx [1-10]`), for one play
    (`/addthis` keeps them); maps that need TMUnlimiter or mix environments are refused. `/tmxinfo` shows what TMX
    knows about the current map, a widget its best TMX times
  - `karma`: players rate the current map with `++` or `--` (in the chat or in a widget at the left), `/karma` shows
    who voted how; the map list (`/list`) shows the votes of every map
  - `jukebox`: players wish the next maps (`/list` opens a window, a click wishes the map; `/jukebox <number>`,
    `/jukebox` shows the wishes); rules: one wish per player, no recently played maps (operators and above: no limits)

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
What pyseco keeps (players, roles, discord links, played maps, the playlist, bans, ...) is defined by the interfaces in
`src/storage/interfaces.py`. The controller and the plugins only use these interfaces, backends implement them:

- `sqlite` (default): one file, `<data_dir>/pyseco.db`. Back it up with `sqlite3 pyseco.db ".backup copy.db"` or
  while pyseco is stopped. This is the only place with SQL (`src/storage/sqlite.py`).
- `memory`: nothing is kept when pyseco stops (tests).

Choose with `backend = "..."` in the `[storage]` section. Logs are in `<data_dir>/logs`.

## Roles and commands
Roles: player, operator, admin, masteradmin. Masteradmins are set in `pyseco.toml`, the others in game
with `/setrole <login> <player|operator|admin>`. `/pyseco` lists the commands you can use.

Discord commands (`!name`) use the role of the TM login the discord account is linked to:
type `/link` in game, then `!link <code>` in the discord channel. `!help` lists them.

## Admin actions
`/admin <action>` (`!admin` on discord) does things directly, while `/skip` and `/replay` stay votes for everybody:
`next`, `replay` (the current map once more, next), `restart` (operators); `remove [<number>]` (takes the current map
or that one off the map list, the file stays), `keep [<number>]` (a temporary TMX map stays) and `save` (admins). In
the `/list` window admins have a button per map for keep or remove. `/admin` lists them. Changes of the map list are
saved in the match settings file set with `matchsettings` in `[maps]`; `/addthis` saves too. The plugin
`admin_panel` puts buttons for these actions at the bottom left for operators and admins.

## Moderation
Always there: `/players` (window; for operators and above a click on a player offers kick, mute, ban), `/kick`,
`/mute`, `/unmute` (operators), `/ban <player> [30m|2h|7d] [reason]`, `/unban`, `/bans` (admins). A player is
found by login or by a part of login or nickname. Bans and mutes are kept and enforced when a player connects.
Nobody can act on a player with the same or a higher role.

## Structure
- `src/core/`: the controller (`controller.py`), the server connection (`server.py`) with the server's methods
  (`server_api.py`), events, commands, roles, settings, log
- `src/services/`: always there, used by plugins: `accounts` (roles, discord links), `players` (who is online),
  `maps` (map list, current map, history), `chat` (messages to players), `ui` and `windows` (manialinks),
  `moderation` (kick, mute, ban), `playlist` (which map comes next: requests from the jukebox, votes, ... are
  queued, temporary maps are removed after they were played; `/nextmap`, `/history`, `/addthis`), `race`
  (checkpoints and finishes of every run)
- `src/storage/`: what pyseco keeps, see Data
- `src/plugins/`: optional features, switched on in `pyseco.toml`

Plugins use the core and the services, never each other. When two plugins need the same thing, it belongs into a service.

## Writing plugins
Derive from `plugins.plugin.Plugin` and add the plugin to `AVAILABLE` in `src/plugins/plugins.py`. In `__init__`:
- settings: `controller.settings('<plugin>')`, the plugin's section of `pyseco.toml` as dict
- events: `controller.events.register(name, handler)`, names in `core/events.py` (see below)
- commands: `controller.commands.register(name, handler, role=roles.ADMIN, help=..., usage=...,
  sources=(commands.GAME, commands.DISCORD))`; the handler gets a `commands.Context` (`ctx.login`, `ctx.args`,
  `await ctx.reply(text)`), raise `commands.UsageError` for wrong arguments
- data: add a store interface for the plugin's data to `src/storage/interfaces.py` (and to `Storage`), implement
  it in every backend (`storage/sqlite.py` with its migrations, `storage/memory.py`) and extend the contract
  tests in `tests/test_storage.py`; the plugin uses `controller.storage.<store>`. In SQLite, never change a
  released migration script, append a new one

Anything that talks to the server or the network belongs into `async def start(self)`.

Server methods are typed: `await controller.server.choose_next_challenge(filename)`, `await
controller.server.get_player_list(100, 0)`; errors of the server raise `xmlrpc.client.Fault`. They are generated
from the dedicated server's `ListMethods.html` by `tools/gen_server_api.py` (parameter names and the returned
structures are listed there). `controller.server.call('Method', ...)` reaches any method directly.
Messages to players: `controller.chat.announce(text)`, `controller.chat.tell(login, text)`.
Images for manialinks: put them into `src/www`; `controller.web.url('name.png')` gives their URL when the web
server is on (`[http]` port and url), otherwise None.

UI (`services/windows.py`), created in `__init__`:
- `ListWindow(controller.ui, columns=[...])`, then `await window.open(login, title, rows, on_click)`: a window
  with a paged list, every player has their own; `on_click(login, index)` makes the rows clickable
- `TextWidget(controller.ui, name, x, y)`, then `await widget.show(text, login=None)`: text at a fixed place;
  server owners can move it with `[widgets.<name>]` (`x`, `y`) in `pyseco.toml`
- anything else: `controller.ui.manialink_id()`, `controller.ui.actions(count, handler)` and
  `await controller.ui.show(id, xml, login)` with the helpers in `services/ui.py`

Handlers are `async` functions. Never block in a handler (no `time.sleep`, no synchronous network calls):
everything shares one event loop.

Events (`core/events.py`): `PLAYER_JOINED` / `PLAYER_LEFT` (a `Player`), `CHAT` (player and text, no commands),
`MAP_STARTED` / `MAP_ENDED` (the map), `MAP_LIST_CHANGED`, `PLAYLIST_CHANGED`, `CHECKPOINT`, `PLAYER_FINISHED`
(with the checkpoints of the run), `SECOND_PASSED`. Raw server callbacks can be registered by their
name (`'TrackMania.Echo'`, ...) and get the callback's parameters.

## Tests
```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```
The tests run the controller against `tests/fake_server.py`, a stand-in for the dedicated server's XML-RPC interface.
