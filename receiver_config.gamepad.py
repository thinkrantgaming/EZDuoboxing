"""Direct gamepad mapping for the v4.9 Windows receiver.
Requires vgamepad + ViGEmBus. No keyboard or mouse actions are enabled.
R5 selects the remote host; it is consumed by the sender.
Extra grips and touchpad sectors have no Xbox equivalents and are unassigned.
LT/RT produce full press/release, not progressive analog pressure.
"""

BINDINGS = {
    'A': {'mode': 'gamepad_hold', 'button': 'A'},
    'B': {'mode': 'gamepad_hold', 'button': 'B'},
    'X': {'mode': 'gamepad_hold', 'button': 'X'},
    'Y': {'mode': 'gamepad_hold', 'button': 'Y'},
    'LB': {'mode': 'gamepad_hold', 'button': 'LB'},
    'RB': {'mode': 'gamepad_hold', 'button': 'RB'},
    'LT': {'mode': 'gamepad_hold', 'button': 'LT'},
    'RT': {'mode': 'gamepad_hold', 'button': 'RT'},
    'BACK': {'mode': 'gamepad_hold', 'button': 'BACK'},
    'START': {'mode': 'gamepad_hold', 'button': 'START'},
    'L3': {'mode': 'gamepad_hold', 'button': 'L3'},
    'R3': {'mode': 'gamepad_hold', 'button': 'R3'},
    'DPAD_UP': {'mode': 'gamepad_hold', 'button': 'DPAD_UP'},
    'DPAD_DOWN': {'mode': 'gamepad_hold', 'button': 'DPAD_DOWN'},
    'DPAD_LEFT': {'mode': 'gamepad_hold', 'button': 'DPAD_LEFT'},
    'DPAD_RIGHT': {'mode': 'gamepad_hold', 'button': 'DPAD_RIGHT'},
}

GAMEPAD_LEFT_STICK = True
GAMEPAD_RIGHT_STICK = True
LEFT_STICK_ENABLED = False
RIGHT_STICK_MOUSE_ENABLED = False

# Required receiver settings; KBM movement/mouse output above is disabled.
MOVEMENT_KEYS = {'up': 'w', 'down': 's', 'left': 'a', 'right': 'd'}
MOVE_PRESS_THRESHOLD = 0.45
MOVE_RELEASE_THRESHOLD = 0.35
MOUSE_DEADZONE = 0.18
MOUSE_MAX_SPEED = 900.0
MOUSE_CURVE = 1.4
MOUSE_INVERT_X = False
MOUSE_INVERT_Y = False
TAP_DURATION_SECONDS = 0.065
LINK_TIMEOUT_SECONDS = 1.0
