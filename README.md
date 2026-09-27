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

## Setup
Requires Python 3.11 or newer.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Edit `src/pyseco.cfg` (xml-rpc port and SuperAdmin password of the dedicated server, plugins).

For the discord plugin copy `src/plugins/discord.ini.example` to `src/plugins/discord.ini` and fill it in.
The bot needs the **Message Content Intent** (Discord developer portal -> your app -> Bot).

Start with `src/pyseco.sh` (runs in the background, output in `src/pyseco.log`)
or in the foreground with `cd src && ../.venv/bin/python pyseco.py`.

`--config-dir DIR` reads `pyseco.cfg` and `plugins/*.ini` from another directory (default: the current one),
e.g. to run one instance per server. SIGTERM (docker, systemd) stops the controller cleanly.

## Writing plugins
Derive from `plugins.plugin.Plugin`, register handlers with `controller.register_event(name, handler)` in `__init__`
and add the plugin to `AVAILABLE` in `src/plugins/plugins.py`.
Handlers are `async` functions; server requests are awaited, e.g. `await self.controller.chat_send('hi')`.
Never block in a handler (no `time.sleep`, no synchronous network calls): everything shares one event loop.

Events: all server callbacks (`TrackMania.PlayerChat`, ...) plus `PlayerConnectComplete` (login),
`PlayerDisconnectComplete` (player object) and `second_passed`.
