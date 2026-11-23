"""EDIT THIS FILE to change remote controls. Restart your Windows or macOS receiver after editing.

Button names: A B X Y LB RB LT RT BACK START L3 R3 L4 L5 R4 R5
              DPAD_UP DPAD_DOWN DPAD_LEFT DPAD_RIGHT
Modes:
  tap        press/release keys once per controller button press
  hold       hold keys as long as controller button stays down
  mouse_tap  click a mouse button (left/right/middle)
  mouse_hold hold a mouse button as long as the controller button stays down

These are examples. Every mapping is independent of the local player’s Steam Input layout.
"""

BINDINGS = {
    'A': {'mode': 'tap', 'keys': ['1']},
    'B': {'mode': 'hold', 'keys': ['shift']},
    'X': {'mode': 'tap', 'keys': ['shift', '2']},
    'Y': {'mode': 'tap', 'keys': ['tab']},

    'DPAD_UP':    {'mode': 'tap', 'keys': ['f1']},
    'DPAD_DOWN':  {'mode': 'tap', 'keys': ['f2']},
    'DPAD_LEFT':  {'mode': 'tap', 'keys': ['f3']},
    'DPAD_RIGHT': {'mode': 'tap', 'keys': ['f4']},

    'LB': {'mode': 'mouse_tap', 'button': 'left'},
    'RB': {'mode': 'mouse_tap', 'button': 'right'},
    'LT': {'mode': 'hold', 'keys': ['ctrl']},
    'RT': {'mode': 'tap', 'keys': ['5']},
    'BACK': {'mode': 'tap', 'keys': ['escape']},
    'START': {'mode': 'tap', 'keys': ['enter']},
    'L3': {'mode': 'tap', 'keys': ['space']},
    'R3': {'mode': 'tap', 'keys': ['m']},

    # Optional native grips: sender --grips, active only while this receiver is selected.
    # Independent native touchpad sectors (sender --touchpads).
    'LPAD_UP': {'mode': 'tap', 'keys': ['f5']},
    'LPAD_DOWN': {'mode': 'tap', 'keys': ['f6']},
    'LPAD_LEFT': {'mode': 'tap', 'keys': ['f7']},
    'LPAD_RIGHT': {'mode': 'tap', 'keys': ['f8']},
    'RPAD_UP': {'mode': 'tap', 'keys': ['f9']},
    'RPAD_DOWN': {'mode': 'tap', 'keys': ['f10']},
    'RPAD_LEFT': {'mode': 'tap', 'keys': ['f11']},
    'RPAD_RIGHT': {'mode': 'tap', 'keys': ['f12']},

    'L4': {'mode': 'tap', 'keys': ['6']},
    'L5': {'mode': 'tap', 'keys': ['7']},
    'R4': {'mode': 'tap', 'keys': ['8']},
    'R5': {'mode': 'tap', 'keys': ['7']},  # Ability when L5 selects this receiver.
}

# LEFT STICK: map stick direction into keys held on the remote host. Typical MMORPG movement.
LEFT_STICK_ENABLED = True
MOVEMENT_KEYS = {'up': 'w', 'down': 's', 'left': 'a', 'right': 'd'}
# Press and release thresholds differ slightly to avoid jitter/chattering.
MOVE_PRESS_THRESHOLD = 0.45
MOVE_RELEASE_THRESHOLD = 0.35

# RIGHT STICK: continuous RELATIVE mouse movement on Windows.
RIGHT_STICK_MOUSE_ENABLED = True
MOUSE_DEADZONE = 0.18          # Stick movement below this is ignored.
MOUSE_MAX_SPEED = 900.0        # Mouse pixels/second when stick is fully tilted.
MOUSE_CURVE = 1.4              # >1 finer slow movements; 1=linear.
MOUSE_INVERT_X = False
MOUSE_INVERT_Y = False

TAP_DURATION_SECONDS = 0.065
LINK_TIMEOUT_SECONDS = 1.0     # Emergency release if no packets for this long.
