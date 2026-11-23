#!/usr/bin/env python3
"""macOS receiver: authenticated Deck input -> foreground keyboard/mouse events.

Requires pyobjc-framework-Quartz and macOS Accessibility permission.
Keep windows_receiver.py alongside this file: it contains the shared bridge and
network loop, and imports no Windows-only dependency unless its main() is run.
"""
import argparse
import sys

import windows_receiver as core

# macOS ANSI virtual key positions, independent of Intel/Apple Silicon.
# Characters produced depend on the selected macOS keyboard layout.
KEY_CODES = {
    'a': 0, 's': 1, 'd': 2, 'f': 3, 'h': 4, 'g': 5, 'z': 6, 'x': 7,
    'c': 8, 'v': 9, 'b': 11, 'q': 12, 'w': 13, 'e': 14, 'r': 15,
    'y': 16, 't': 17, '1': 18, '2': 19, '3': 20, '4': 21, '6': 22,
    '5': 23, '=': 24, '9': 25, '7': 26, '-': 27, '8': 28, '0': 29,
    ']': 30, 'o': 31, 'u': 32, '[': 33, 'i': 34, 'p': 35,
    'enter': 36, 'l': 37, 'j': 38, "'": 39, 'k': 40, ';': 41,
    '\\': 42, ',': 43, '/': 44, 'n': 45, 'm': 46, '.': 47,
    'tab': 48, 'space': 49, '`': 50, 'backspace': 51, 'escape': 53,
    'command': 55, 'shift': 56, 'alt': 58, 'ctrl': 59,
    'commandright': 54, 'shiftright': 60, 'altright': 61, 'ctrlright': 62,
    'decimal': 65, 'multiply': 67, 'add': 69, 'divide': 75,
    'numenter': 76, 'subtract': 78, 'numequal': 81,
    'num0': 82, 'num1': 83, 'num2': 84, 'num3': 85, 'num4': 86,
    'num5': 87, 'num6': 88, 'num7': 89, 'num8': 91, 'num9': 92,
    'f1': 122, 'f2': 120, 'f3': 99, 'f4': 118, 'f5': 96, 'f6': 97,
    'f7': 98, 'f8': 100, 'f9': 101, 'f10': 109, 'f11': 103, 'f12': 111,
    'f13': 105, 'f14': 107, 'f15': 113, 'f16': 106, 'f17': 64,
    'f18': 79, 'f19': 80, 'f20': 90,
    'home': 115, 'pageup': 116, 'delete': 117, 'end': 119, 'pagedown': 121,
    'left': 123, 'right': 124, 'down': 125, 'up': 126,
}
ALIASES = {
    'return': 'enter', 'esc': 'escape', 'spacebar': 'space',
    'control': 'ctrl', 'ctrlleft': 'ctrl', 'shiftleft': 'shift',
    'option': 'alt', 'altleft': 'alt', 'optionright': 'altright',
    'cmd': 'command', 'win': 'command', 'winleft': 'command',
    'commandleft': 'command', 'winright': 'commandright',
    'del': 'delete', 'pgup': 'pageup', 'pgdn': 'pagedown',
}


def key_code(name):
    if not isinstance(name, str):
        raise ValueError(f'macOS key must be a string: {name!r}')
    name = ALIASES.get(name.lower(), name.lower())
    if name not in KEY_CODES:
        raise ValueError(f'Unsupported macOS key: {name!r}. Use an unshifted key with a modifier, e.g. ["shift", "1"].')
    return KEY_CODES[name]


def validate_mac_bindings(config):
    for name, binding in config.BINDINGS.items():
        if binding['mode'] in ('tap', 'hold'):
            for key in binding['keys']:
                try:
                    key_code(key)
                except ValueError as exc:
                    raise ValueError(f'{name}: {exc}') from exc
    if config.LEFT_STICK_ENABLED:
        for key in config.MOVEMENT_KEYS.values():
            key_code(key)


class MacInput:
    """Small adapter matching InputBridge's existing keyboard/mouse interface."""
    def __init__(self, quartz):
        self.q = quartz
        self.source = quartz.CGEventSourceCreate(quartz.kCGEventSourceStatePrivate)
        if self.source is None:
            raise RuntimeError('macOS could not create an input event source')
        self.keys = {}  # Count aliases sharing a physical key.
        self.mouse_buttons = set()
        self.modifiers = {
            56: quartz.kCGEventFlagMaskShift, 60: quartz.kCGEventFlagMaskShift,
            59: quartz.kCGEventFlagMaskControl, 62: quartz.kCGEventFlagMaskControl,
            58: quartz.kCGEventFlagMaskAlternate, 61: quartz.kCGEventFlagMaskAlternate,
            55: quartz.kCGEventFlagMaskCommand, 54: quartz.kCGEventFlagMaskCommand,
        }

    def flags(self):
        flags = 0
        for code in self.keys:
            flags |= self.modifiers.get(code, 0)
        return flags

    def post(self, event):
        if event is None:
            raise RuntimeError('macOS could not create an input event')
        self.q.CGEventSetFlags(event, self.flags())
        self.q.CGEventPost(self.q.kCGHIDEventTap, event)

    def keyDown(self, key):
        code = key_code(key)
        self.keys[code] = self.keys.get(code, 0) + 1
        if self.keys[code] == 1:
            self.post(self.q.CGEventCreateKeyboardEvent(self.source, code, True))

    def keyUp(self, key):
        code = key_code(key)
        count = self.keys.get(code, 0)
        if count <= 0:
            return
        if count > 1:
            self.keys[code] = count - 1
        else:
            del self.keys[code]
            self.post(self.q.CGEventCreateKeyboardEvent(self.source, code, False))

    def position(self):
        event = self.q.CGEventCreate(None)
        if event is None:
            raise RuntimeError('macOS could not read pointer position')
        point = self.q.CGEventGetLocation(event)
        return point.x, point.y

    def mouse_event(self, button, action, position):
        q = self.q
        names = {'left': ('Left', q.kCGMouseButtonLeft),
                 'right': ('Right', q.kCGMouseButtonRight),
                 'middle': ('Other', q.kCGMouseButtonCenter)}
        prefix, number = names[button]
        event_type = getattr(q, 'kCGEvent' + prefix + 'Mouse' + action)
        return q.CGEventCreateMouseEvent(self.source, event_type, position, number)

    def mouseDown(self, button):
        if button not in self.mouse_buttons:
            self.mouse_buttons.add(button)
            event = self.mouse_event(button, 'Down', self.position())
            self.q.CGEventSetIntegerValueField(event, self.q.kCGMouseEventClickState, 1)
            self.post(event)

    def mouseUp(self, button):
        if button in self.mouse_buttons:
            self.mouse_buttons.remove(button)
            event = self.mouse_event(button, 'Up', self.position())
            self.q.CGEventSetIntegerValueField(event, self.q.kCGMouseEventClickState, 1)
            self.post(event)

    def moveRel(self, dx, dy, relative=True, _pause=False):
        q = self.q
        x, y = self.position()
        position = (x + dx, y + dy)
        # A held mouse button needs a drag event, rather than a plain move.
        button = next((b for b in ('left', 'right', 'middle') if b in self.mouse_buttons), None)
        if button:
            event = self.mouse_event(button, 'Dragged', position)
        else:
            event = q.CGEventCreateMouseEvent(self.source, q.kCGEventMouseMoved, position, q.kCGMouseButtonLeft)
        q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaX, int(dx))
        q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaY, int(dy))
        self.post(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sender-ip', '--deck-ip', dest='deck_ip', required=True)
    parser.add_argument('--port', type=int, default=50505)
    parser.add_argument('--token', default='CHANGE_THIS_PRIVATE_TOKEN')
    parser.add_argument('--controls', help='Trusted receiver controls Python file')
    parser.add_argument('--debug-axes', action='store_true')
    args = parser.parse_args()
    if args.controls:
        import runpy
        from types import SimpleNamespace
        core.config = SimpleNamespace(**runpy.run_path(args.controls))
    if sys.platform != 'darwin':
        parser.error('Run macos_receiver.py on macOS; use windows_receiver.py on Windows')
    try:
        import Quartz
    except ImportError:
        sys.exit('Install the Mac dependency: python3 -m pip install pyobjc-framework-Quartz')
    try:
        core.validate_config()
        validate_mac_bindings(core.config)
    except ValueError as exc:
        parser.error(str(exc))
    if not Quartz.CGPreflightPostEventAccess():
        sys.exit('Accessibility permission is required. Enable the terminal app running this receiver '\
                 'in System Settings > Privacy & Security > Accessibility, then quit/reopen it and retry. '\
                 'If macOS identifies Python separately, grant that executable access too.')
    core.run_receiver(MacInput(Quartz), args, 'macOS')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.')
