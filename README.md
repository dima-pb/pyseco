# pyseco
An attempt to create a poor-mans aseco for TMF in python


A controller for TMF Servers, written in python.
Supports rpc calls (though most are yet to be defined) and callbacks from the server.

Supports plugins (I shamelessly stole the architecture for those from (x)aseco)
Currently two plugins are implemented:
  - A discord bot that synchronises chat of a Trackmania server with a discord channel-chat.
  - A custom votes plugin that uses the native TMF voting engine. Currently only the usual replay and skip votes implemented,
    but more can very easily be added

