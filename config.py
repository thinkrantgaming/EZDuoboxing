"""Public sender example. Copy to config.local.py, edit, use --config config.local.py.
Positional receiver IP bypasses this file and fixes the selector to R5.
"""
TOKEN = 'CHANGE_THIS_PRIVATE_TOKEN'
HOSTS = {
    'host1': {'ip': 'RECEIVER_1_IP', 'port': 50505, 'button': 'R5', 'enabled': True},
    'host2': {'ip': 'RECEIVER_2_IP', 'port': 50505, 'button': 'L5', 'enabled': False},
}
INPUT_SOURCE = 'native'  # Deck only: native physical input; virtual keeps older layouts.
GRIPS = True
TOUCHPADS = 'pressure'
