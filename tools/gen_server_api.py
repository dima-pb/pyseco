#!/usr/bin/env python3
# Generates src/core/server_api.py, the typed methods of the dedicated server, from the server's own
# method list (ListMethods.html, shipped with the dedicated server; the same as system.methodSignature
# and system.methodHelp report).
#
# Usage: tools/gen_server_api.py <path to ListMethods.html> > src/core/server_api.py
#
# The method list only knows types, so parameter names (and defaults of optional parameters) come from
# PARAMS below; the structures the server returns from STRUCTS and RETURNS.

import html
import re
import sys


TYPES = {'boolean': 'bool', 'int': 'int', 'string': 'str', 'double': 'float', 'base64': 'xmlrpc.client.Binary',
  'array': 'list', 'struct': 'dict'}

# method -> parameter names in order, optional ones with their default
PARAMS = {
  'Authenticate': 'login, password',
  'ChangeAuthPassword': 'login, password',
  'EnableCallbacks': 'enable',
  'CallVote': 'command_xml',
  'CallVoteEx': 'command_xml, ratio, timeout, voter',
  'SetCallVoteTimeOut': 'timeout',
  'SetCallVoteRatio': 'ratio',
  'SetCallVoteRatios': 'ratios',
  'ChatSendServerMessage': 'text',
  'ChatSendServerMessageToLanguage': 'messages, login',
  'ChatSendServerMessageToId': 'text, player_id',
  'ChatSendServerMessageToLogin': 'text, login',
  'ChatSend': 'text',
  'ChatSendToLanguage': 'messages, login',
  'ChatSendToLogin': 'text, login',
  'ChatSendToId': 'text, player_id',
  'ChatEnableManualRouting': 'enable, forward_server_messages',
  'ChatForwardToLogin': 'text, sender_login, dest_login',
  'SendNotice': 'text, avatar_login, duration',
  'SendNoticeToId': 'player_id, text, avatar_id, duration',
  'SendNoticeToLogin': 'login, text, avatar_login, duration',
  'SendDisplayManialinkPage': 'xml, timeout, hide_on_click',
  'SendDisplayManialinkPageToId': 'player_id, xml, timeout, hide_on_click',
  'SendDisplayManialinkPageToLogin': 'login, xml, timeout, hide_on_click',
  'SendHideManialinkPageToId': 'player_id',
  'SendHideManialinkPageToLogin': 'login',
  'Kick': "login, message=''",
  'KickId': "player_id, message=''",
  'Ban': "login, message=''",
  'BanAndBlackList': 'login, message, save',
  'BanId': "player_id, message=''",
  'UnBan': 'login',
  'GetBanList': 'count, start',
  'BlackList': 'login',
  'BlackListId': 'player_id',
  'UnBlackList': 'login',
  'GetBlackList': 'count, start',
  'LoadBlackList': 'filename',
  'SaveBlackList': 'filename',
  'AddGuest': 'login',
  'AddGuestId': 'player_id',
  'RemoveGuest': 'login',
  'RemoveGuestId': 'player_id',
  'GetGuestList': 'count, start',
  'LoadGuestList': 'filename',
  'SaveGuestList': 'filename',
  'SetBuddyNotification': 'login, enabled',
  'GetBuddyNotification': 'login',
  'WriteFile': 'filename, data',
  'TunnelSendDataToId': 'player_id, data',
  'TunnelSendDataToLogin': 'login, data',
  'Echo': 'first, second',
  'Ignore': 'login',
  'IgnoreId': 'player_id',
  'UnIgnore': 'login',
  'UnIgnoreId': 'player_id',
  'GetIgnoreList': 'count, start',
  'Pay': 'login, coppers, label',
  'SendBill': 'login_from, coppers, label, login_to',
  'GetBillState': 'bill_id',
  'SetConnectionRates': 'download, upload',
  'SetServerName': 'name',
  'SetServerComment': 'comment',
  'SetHideServer': 'hidden',
  'SetServerPassword': 'password',
  'SetServerPasswordForSpectator': 'password',
  'SetMaxPlayers': 'count',
  'SetMaxSpectators': 'count',
  'EnableP2PUpload': 'enable',
  'EnableP2PDownload': 'enable',
  'AllowChallengeDownload': 'allow',
  'AutoSaveReplays': 'enable',
  'AutoSaveValidationReplays': 'enable',
  'SaveCurrentReplay': "filename=''",
  'SaveBestGhostsReplay': "login, filename=''",
  'GetValidationReplay': 'login',
  'SetLadderMode': 'mode',
  'SetVehicleNetQuality': 'quality',
  'SetServerOptions': 'options',
  'GetServerOptions': 'version=1',
  'SetServerPackMask': 'pack_mask',
  'SetForcedMods': 'override, mods',
  'SetForcedMusic': 'override, url_or_filename',
  'SetForcedSkins': 'skins',
  'SetRefereePassword': 'password',
  'SetRefereeMode': 'mode',
  'SetUseChangingValidationSeed': 'enable',
  'SetWarmUp': 'enable',
  'SetGameInfos': 'game_infos',
  'GetCurrentGameInfo': 'version=1',
  'GetNextGameInfo': 'version=1',
  'GetGameInfos': 'version=1',
  'SetGameMode': 'mode',
  'SetChatTime': 'ms',
  'SetFinishTimeout': 'ms',
  'SetAllWarmUpDuration': 'rounds',
  'SetDisableRespawn': 'disable',
  'SetForceShowAllOpponents': 'count',
  'SetTimeAttackLimit': 'ms',
  'SetTimeAttackSynchStartPeriod': 'ms',
  'SetLapsTimeLimit': 'ms',
  'SetNbLaps': 'laps',
  'SetRoundForcedLaps': 'laps',
  'SetRoundPointsLimit': 'points',
  'SetRoundCustomPoints': 'points, relax',
  'SetUseNewRulesRound': 'enable',
  'SetTeamPointsLimit': 'points',
  'SetMaxPointsTeam': 'points',
  'SetUseNewRulesTeam': 'enable',
  'SetCupPointsLimit': 'points',
  'SetCupRoundsPerChallenge': 'rounds',
  'SetCupWarmUpDuration': 'rounds',
  'SetCupNbWinners': 'count',
  'SetNextChallengeIndex': 'index',
  'GetChallengeInfo': 'filename',
  'CheckChallengeForCurrentServerParams': 'filename',
  'GetChallengeList': 'count, start',
  'AddChallenge': 'filename',
  'AddChallengeList': 'filenames',
  'RemoveChallenge': 'filename',
  'RemoveChallengeList': 'filenames',
  'InsertChallenge': 'filename',
  'InsertChallengeList': 'filenames',
  'ChooseNextChallenge': 'filename',
  'ChooseNextChallengeList': 'filenames',
  'LoadMatchSettings': 'filename',
  'AppendPlaylistFromMatchSettings': 'filename',
  'SaveMatchSettings': 'filename',
  'InsertPlaylistFromMatchSettings': 'filename',
  'GetPlayerList': 'count, start, version=1',
  'GetPlayerInfo': 'login, version=1',
  'GetDetailedPlayerInfo': 'login',
  'GetMainServerPlayerInfo': 'version=1',
  'GetCurrentRanking': 'count, start',
  'GetCurrentRankingForLogin': 'login',
  'ForceScores': 'scores, silent',
  'ForcePlayerTeam': 'login, team',
  'ForcePlayerTeamId': 'player_id, team',
  'ForceSpectator': 'login, mode',
  'ForceSpectatorId': 'player_id, mode',
  'ForceSpectatorTarget': 'spectator_login, target_login, camera',
  'ForceSpectatorTargetId': 'spectator_id, target_id, camera',
  'SpectatorReleasePlayerSlot': 'login',
  'SpectatorReleasePlayerSlotId': 'player_id',
  'ManualFlowControlEnable': 'enable',
  'StartServerInternet': 'account',
}

# structures the server returns; fields as the method help lists them
STRUCTS = {
  'ChallengeInfo': [('UId', 'str'), ('Name', 'str'), ('FileName', 'str'), ('Author', 'str'), ('Environnement', 'str'),
    ('Mood', 'str'), ('BronzeTime', 'int'), ('SilverTime', 'int'), ('GoldTime', 'int'), ('AuthorTime', 'int'),
    ('CopperPrice', 'int'), ('LapRace', 'bool'), ('NbLaps', 'int'), ('NbCheckpoints', 'int')],
  'PlayerInfo': [('Login', 'str'), ('NickName', 'str'), ('PlayerId', 'int'), ('TeamId', 'int'), ('SpectatorStatus', 'int'),
    ('LadderRanking', 'int'), ('Flags', 'int')],
  'PlayerRanking': [('Login', 'str'), ('NickName', 'str'), ('PlayerId', 'int'), ('Rank', 'int'), ('BestTime', 'int'),
    ('BestCheckpoints', 'list[int]'), ('Score', 'int'), ('NbrLapsFinished', 'int'), ('LadderScore', 'float')],
  'Version': [('Name', 'str'), ('Version', 'str'), ('Build', 'str')],
  'Status': [('Code', 'int'), ('Name', 'str')],
  'CallVote': [('CallerLogin', 'str'), ('CmdName', 'str'), ('CmdParam', 'str')],
}
STRUCT_DOCS = {
  'ChallengeInfo': 'A map. GetChallengeList only fills UId, Name, FileName, Environnement, Author, GoldTime and CopperPrice.',
  'PlayerInfo': 'Flags = ForceSpectator(0,1,2) + IsReferee * 10 + IsPodiumReady * 100 + IsUsingStereoscopy * 1000\n'
    '  #   + IsManagedByAnOtherServer * 10000 + IsServer * 100000 + HasPlayerSlot * 1000000\n'
    '  # SpectatorStatus = Spectator + TemporarySpectator * 10 + PureSpectator * 100 + AutoTarget * 1000\n'
    '  #   + CurrentTargetId * 10000',
}

RETURNS = {
  'GetCurrentChallengeInfo': 'ChallengeInfo',
  'GetNextChallengeInfo': 'ChallengeInfo',
  'GetChallengeInfo': 'ChallengeInfo',
  'GetChallengeList': 'list[ChallengeInfo]',
  'GetPlayerInfo': 'PlayerInfo',
  'GetPlayerList': 'list[PlayerInfo]',
  'GetCurrentRanking': 'list[PlayerRanking]',
  'GetCurrentRankingForLogin': 'list[PlayerRanking]',
  'GetVersion': 'Version',
  'GetStatus': 'Status',
  'GetCurrentCallVote': 'CallVote',
}


def snake_case(name):
  name = name.replace('P2P', 'P2p')
  name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
  name = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
  return name.lower()
#


def wrap(text, indent, width=110):
  lines, line = [], ''
  for word in text.split():
    if line and len(indent) + len(line) + 1 + len(word) > width:
      lines.append(line)
      line = word
    else:
      line = (line + ' ' + word).strip()
    #
  #
  if line:
    lines.append(line)
  #
  return lines
#


def main():
  source = open(sys.argv[1], encoding='latin-1').read()
  methods = re.findall(r"<li><b>(.*?)</b><br/>\s*(.*?)<br/>\s*<font[^>]*>(.*?)</font>", source, re.S)
  out = []
  out.append('# Generated by tools/gen_server_api.py from the dedicated server\'s ListMethods.html - do not edit.')
  out.append('# The typed methods of the dedicated server (TMF, 2011-02-21). Errors of the server raise')
  out.append('# xmlrpc.client.Fault. Structures are TypedDicts: plain dicts at runtime, typed for IDEs and mypy.')
  out.append('')
  out.append('import xmlrpc.client')
  out.append('from typing import TypedDict')
  out.append('')
  out.append('')
  for name, fields in STRUCTS.items():
    out.append('class ' + name + '(TypedDict, total=False):')
    if name in STRUCT_DOCS:
      out.append('  # ' + STRUCT_DOCS[name])
    #
    for field, kind in fields:
      out.append('  ' + field + ': ' + kind)
    #
    out.append('#')
    out.append('')
    out.append('')
  #
  out.append('class ServerApi:')
  out.append('  # Subclasses implement call(method, *params).')
  out.append('')
  out.append('  async def call(self, method, *params):')
  out.append('    raise NotImplementedError')
  out.append('  #')
  for name, signature, help in methods:
    if name.startswith('system.'):
      continue
    #
    match = re.match(r'(\w+) ([\w.]+)\((.*)\)', signature.strip())
    returns, types = match.group(1), [t.strip() for t in match.group(3).split(',') if t.strip()]
    names = [p.strip() for p in PARAMS.get(name, '').split(',') if p.strip()]
    if len(names) != len(types):
      raise SystemExit(name + ': ' + str(len(types)) + ' parameters, PARAMS names ' + str(len(names)))
    #
    params, args = [], []
    for param, kind in zip(names, types):
      param, _, default = param.partition('=')
      params.append(param + ': ' + TYPES[kind] + (' = ' + default if default else ''))
      args.append(param)
    #
    result = RETURNS.get(name, TYPES[returns])
    out.append('')
    out.append('  async def ' + snake_case(name) + '(' + ', '.join(['self'] + params) + ') -> ' + result + ':')
    text = re.sub(r'<[^>]+>', '', html.unescape(help)).strip()
    out.append('    """' + '\n    '.join(wrap(text, '    ')) + '"""')
    out.append('    return await self.call(' + ', '.join(["'" + name + "'"] + args) + ')')
    out.append('  #')
  #
  out.append('#')
  print('\n'.join(out))
#


if __name__ == '__main__':
  main()
#
