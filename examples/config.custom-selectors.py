"""Copy to the repository root as config.local.py and replace IP/token placeholders."""
TOKEN = 'CHANGE_THIS_PRIVATE_TOKEN'
HOSTS = {
    'host1': {'ip': 'RECEIVER_1_IP', 'port': 50505, 'button': 'LB', 'enabled': True},
    'host2': {'ip': 'RECEIVER_2_IP', 'port': 50505, 'button': 'BACK', 'enabled': True},
}
INPUT_SOURCE = 'native'
GRIPS = True
TOUCHPADS = 'pressure'
