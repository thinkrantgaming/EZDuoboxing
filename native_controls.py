"""Physical controls, independent of Steam Input. Layouts: SDL Steam Deck/Triton.
Protocol references are listed in docs/SETUP.md. No feature writes.
"""
import struct
from sender_common import AXIS_NAMES, normalize_native_report

DECK_BITS = {2: 'RB', 3: 'LB', 4: 'Y', 5: 'B', 6: 'X', 7: 'A',
             8: 'DPAD_UP', 9: 'DPAD_RIGHT', 10: 'DPAD_LEFT', 11: 'DPAD_DOWN',
             12: 'BACK', 14: 'START', 22: 'L3', 26: 'R3'}
STEAM_BITS = {0: 'A', 1: 'B', 2: 'X', 3: 'Y', 5: 'R3', 6: 'START',
              9: 'RB', 10: 'DPAD_DOWN', 11: 'DPAD_RIGHT', 12: 'DPAD_LEFT',
              13: 'DPAD_UP', 14: 'BACK', 15: 'L3', 19: 'LB'}


class NativeControls:
    def __init__(self, controller='deck'):
        self.controller = controller
        self.buttons = set()
        self.triggers = set()
        self.axes = dict.fromkeys(AXIS_NAMES, 0.0)

    def update(self, raw):
        if normalize_native_report(raw, self.controller) is None: return False
        before = self.buttons.copy()
        if self.controller == 'deck':
            bits = struct.unpack_from('<I', raw, 8)[0]
            mapping = DECK_BITS
            triggers = struct.unpack_from('<HH', raw, 44)
            values = struct.unpack_from('<hhhh', raw, 48)
            trigger_max = 32767.0
        else:
            bits = struct.unpack_from('<I', raw, 2)[0]
            mapping = STEAM_BITS
            triggers = struct.unpack_from('<hh', raw, 6)
            values = struct.unpack_from('<hhhh', raw, 10)
            trigger_max = 32767.0
        for name, value in zip(('LT', 'RT'), triggers):
            if value / trigger_max >= .55: self.triggers.add(name)
            elif value / trigger_max <= .40: self.triggers.discard(name)
        self.buttons = {name for bit, name in mapping.items() if bits & (1 << bit)} | self.triggers
        self.axes = {name: round(max(-1., min(1., value / 32767.)) * (-1 if name.endswith('Y') else 1), 4)
                     for name, value in zip(AXIS_NAMES, values)}
        return before != self.buttons

    def snapshot(self):
        return dict(buttons=sorted(self.buttons), axes=self.axes.copy())
