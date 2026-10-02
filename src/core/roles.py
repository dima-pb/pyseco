# roles, higher includes lower
PLAYER = 0
OPERATOR = 1
ADMIN = 2
MASTERADMIN = 3

NAMES = {PLAYER: 'player', OPERATOR: 'operator', ADMIN: 'admin', MASTERADMIN: 'masteradmin'}
BY_NAME = {name: role for role, name in NAMES.items()}
