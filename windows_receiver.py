#!/usr/bin/env python3
"""Windows 11: receive virtual Xbox pad state and inject healer keyboard/mouse.

Change key mappings and analog behavior in receiver_config.py, not this file.
Requires: py -m pip install pydirectinput
"""
import argparse
from collections import deque
import hashlib
import hmac
import json
import math
import socket
import sys
import time
from gamepad_output import GamepadOutput, TARGETS, needed as gamepad_needed

try:
    import receiver_config as config
except ImportError:
    sys.exit('Missing receiver_config.py; place it next to windows_receiver.py')

AXES = ('LX', 'LY', 'RX', 'RY')
KNOWN_BUTTONS = {'A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'BACK', 'START',
                 'L3', 'R3', 'L4', 'L5', 'R4', 'R5', 'DPAD_UP', 'DPAD_DOWN', 'DPAD_LEFT', 'DPAD_RIGHT'}

KNOWN_BUTTONS.update(pad + '_' + direction for pad in ('LPAD', 'RPAD')
                     for direction in ('UP', 'DOWN', 'LEFT', 'RIGHT'))


def decode_packet(packet, token):
    """Validate HMAC, data types and protocol version; reject invalid packets."""
    try:
        digest, body = packet.split(b'|', 1)
        expected = hmac.new(token.encode('utf-8'), body, hashlib.sha256).hexdigest().encode('ascii')
        if not hmac.compare_digest(digest, expected):
            return None
        msg = json.loads(body.decode('utf-8'))
        if msg.get('v') != 4 or type(msg.get('seq')) is not int or msg['seq'] < 0:
            return None
        if not isinstance(msg.get('session'), str) or not 1 <= len(msg['session']) <= 64:
            return None
        if not isinstance(msg.get('buttons'), list) or len(msg['buttons']) > 32:
            return None
        if not all(isinstance(b, str) and b in KNOWN_BUTTONS for b in msg['buttons']):
            return None
        if 'healer_active' in msg and type(msg['healer_active']) is not bool:
            return None
        raw = msg.get('axes')
        if not isinstance(raw, dict) or any(k not in raw for k in AXES):
            return None
        for k in AXES:
            v = raw[k]
            if type(v) not in (float, int) or not math.isfinite(v) or not (-1.01 <= v <= 1.01):
                return None
        return msg
    except (ValueError, UnicodeDecodeError, AttributeError, TypeError, KeyError):
        return None

class InputBridge:
    def __init__(self, input_api, debug_axes=False):
        self.gamepad = GamepadOutput() if gamepad_needed(config) else None
        self.api = input_api
        self.debug_axes = debug_axes
        self.buttons = set()
        self.hold_bindings = {}
        self.refs = {}             # Reference counts allow Shift+B plus Shift+2.
        self.pending_taps = []    # (release_time, kind, names)
        self.movement = set()
        self.axes = {k: 0.0 for k in AXES}
        self.mouse_fraction_x = self.mouse_fraction_y = 0.0
        self.last_axes_debug = 0.0

    def down(self, kind, key):
        ident = (kind, key)
        count = self.refs.get(ident, 0)
        if count == 0:
            if kind == 'gamepad': self.gamepad.button(key, True)
            elif kind == 'key': self.api.keyDown(key)
            else: self.api.mouseDown(button=key)
        self.refs[ident] = count + 1

    def up(self, kind, key):
        ident = (kind, key)
        count = self.refs.get(ident, 0)
        if count <= 0: return
        if count == 1:
            if kind == 'gamepad': self.gamepad.button(key, False)
            elif kind == 'key': self.api.keyUp(key)
            else: self.api.mouseUp(button=key)
            self.refs.pop(ident, None)
        else:
            self.refs[ident] = count - 1

    def button_down(self, action, now):
        binding = config.BINDINGS.get(action)
        if not binding: return
        mode = binding['mode']
        kind = 'gamepad' if mode.startswith('gamepad_') else ('mouse' if mode.startswith('mouse_') else 'key')
        names = (binding['button'],) if kind in ('mouse', 'gamepad') else tuple(binding['keys'])
        if mode in ('hold', 'mouse_hold', 'gamepad_hold'):
            self.hold_bindings[action] = (kind, names)
        for name in names: self.down(kind, name)
        if mode in ('tap', 'mouse_tap', 'gamepad_tap'):
            self.pending_taps.append((now + config.TAP_DURATION_SECONDS, kind, names))
        print(f'{action} down -> {mode}: {"+".join(names)}', flush=True)

    def button_up(self, action):
        binding = self.hold_bindings.pop(action, None)
        if binding:
            kind, names = binding
            for name in reversed(names): self.up(kind, name)
            print(f'{action} up -> release {"+".join(names)}', flush=True)

    def update_state(self, buttons, axes, now):
        new_buttons = set(buttons)
        # Release first before new downs (especially when changing hotbars).
        for action in sorted(self.buttons - new_buttons): self.button_up(action)
        for action in sorted(new_buttons - self.buttons): self.button_down(action, now)
        self.buttons = new_buttons
        self.axes = {name: float(axes[name]) for name in AXES}
        self.update_movement()
        if self.gamepad:
            self.gamepad.axes(self.axes, getattr(config, "GAMEPAD_LEFT_STICK", False),
                              getattr(config, "GAMEPAD_RIGHT_STICK", False))
        if self.debug_axes and now - self.last_axes_debug >= 0.25:
            print('Axes: ' + ' '.join(f'{k}={v:+.2f}' for k, v in self.axes.items()), flush=True)
            self.last_axes_debug = now

    def update_movement(self):
        wanted = set()
        if config.LEFT_STICK_ENABLED:
            x, y = self.axes['LX'], self.axes['LY']
            # Add hysteresis: existing direction stays active until release threshold.
            for direction, magnitude in [('up', -y), ('down', y), ('left', -x), ('right', x)]:
                threshold = config.MOVE_RELEASE_THRESHOLD if direction in self.movement else config.MOVE_PRESS_THRESHOLD
                if magnitude >= threshold: wanted.add(direction)
        for direction in self.movement - wanted:
            self.up('key', config.MOVEMENT_KEYS[direction])
        for direction in wanted - self.movement:
            self.down('key', config.MOVEMENT_KEYS[direction])
        if wanted != self.movement:
            print('Left stick movement: ' + (', '.join(sorted(wanted)) or 'released'), flush=True)
        self.movement = wanted

    def tick(self, now, dt):
        outstanding = []
        for due, kind, names in self.pending_taps:
            if now >= due:
                for name in reversed(names): self.up(kind, name)
            else:
                outstanding.append((due, kind, names))
        self.pending_taps = outstanding
        if not config.RIGHT_STICK_MOUSE_ENABLED: return
        def response(v):
            absv = abs(v)
            if absv <= config.MOUSE_DEADZONE: return 0.0
            fraction = (absv - config.MOUSE_DEADZONE) / (1.0 - config.MOUSE_DEADZONE)
            return math.copysign(fraction ** config.MOUSE_CURVE, v)
        dx = response(self.axes['RX']) * config.MOUSE_MAX_SPEED * dt
        dy = response(self.axes['RY']) * config.MOUSE_MAX_SPEED * dt
        if config.MOUSE_INVERT_X: dx = -dx
        if config.MOUSE_INVERT_Y: dy = -dy
        self.mouse_fraction_x += dx
        self.mouse_fraction_y += dy
        whole_x = math.trunc(self.mouse_fraction_x)
        whole_y = math.trunc(self.mouse_fraction_y)
        self.mouse_fraction_x -= whole_x
        self.mouse_fraction_y -= whole_y
        if whole_x or whole_y:
            # Relative SendInput movement. Some games ignore injected mouse-look;
            # verify in MMORPG before depending on it.
            self.api.moveRel(whole_x, whole_y, relative=True, _pause=False)

    def release_all(self):
        # Do not let held Shift / WASD / mouse buttons survive loss of Wi-Fi.
        for action in list(self.hold_bindings): self.button_up(action)
        for direction in list(self.movement):
            self.up('key', config.MOVEMENT_KEYS[direction])
        for _due, kind, names in self.pending_taps:
            for name in reversed(names): self.up(kind, name)
        self.pending_taps.clear()
        # Last-resort cleanup for unexpected reference imbalance.
        for (kind, key) in list(self.refs):
            if kind == 'gamepad': self.gamepad.button(key, False)
            elif kind == 'key': self.api.keyUp(key)
            else: self.api.mouseUp(button=key)
        if self.gamepad: self.gamepad.reset()
        self.refs.clear()
        self.buttons.clear()
        self.movement.clear()
        self.axes = {k: 0.0 for k in AXES}
        self.mouse_fraction_x = self.mouse_fraction_y = 0.0


class ReceiverSession:
    """Keep ordering across outages; release old state before a sender restart."""
    def __init__(self, bridge):
        self.bridge = bridge
        self.session = None
        self.last_seq = -1
        self.last_valid = 0.0
        self.connected = False
        self.retired = deque(maxlen=128)

    def accept(self, message, now):
        session = message['session']
        if session in self.retired:
            return False
        if session != self.session:
            if self.session is not None:
                self.retired.append(self.session)
            self.bridge.release_all()
            self.session, self.last_seq = session, -1
            self.connected = False
        if message['seq'] <= self.last_seq:
            return False
        self.last_seq, self.last_valid = message['seq'], now
        if not self.connected:
            print('Receiving sender input (connected/reconnected).', flush=True)
        self.connected = True
        if message.get('healer_active', True):
            self.bridge.update_state(message['buttons'], message['axes'], now)
        else:
            # Cancel taps as well as holds when the route selector is released or unreadable.
            self.bridge.release_all()
        return True

    def tick(self, now):
        if self.connected and now - self.last_valid > config.LINK_TIMEOUT_SECONDS:
            print('Link timeout -> all keys/mouse buttons released; waiting for sender.', flush=True)
            self.disconnect()

    def disconnect(self):
        self.bridge.release_all()
        self.connected = False
        # Keep session/sequence: an old duplicate must not revive held input.


def validate_config():
    for field in ('GAMEPAD_LEFT_STICK', 'GAMEPAD_RIGHT_STICK'):
        if type(getattr(config, field, False)) is not bool: raise ValueError(f'{field} must be True or False')
    if getattr(config, 'GAMEPAD_LEFT_STICK', False) and config.LEFT_STICK_ENABLED:
        raise ValueError('Disable LEFT_STICK_ENABLED when GAMEPAD_LEFT_STICK is True')
    if getattr(config, 'GAMEPAD_RIGHT_STICK', False) and config.RIGHT_STICK_MOUSE_ENABLED:
        raise ValueError('Disable RIGHT_STICK_MOUSE_ENABLED when GAMEPAD_RIGHT_STICK is True')
    if not 0 <= config.MOUSE_DEADZONE < 1: raise ValueError('MOUSE_DEADZONE must be between 0 and 1')
    if not 0 < config.MOVE_RELEASE_THRESHOLD < config.MOVE_PRESS_THRESHOLD <= 1:
        raise ValueError('Movement thresholds must be 0 < release < press <= 1')
    if config.MOUSE_CURVE <= 0 or config.MOUSE_MAX_SPEED < 0:
        raise ValueError('Mouse curve must be positive; speed must be nonnegative')
    if config.TAP_DURATION_SECONDS <= 0 or config.LINK_TIMEOUT_SECONDS <= 0:
        raise ValueError('Tap and timeout values must be positive')
    for name, bind in config.BINDINGS.items():
        if name not in KNOWN_BUTTONS: raise ValueError(f'Unknown button: {name}')
        if bind.get('mode') not in ('tap', 'hold', 'mouse_tap', 'mouse_hold', 'gamepad_tap', 'gamepad_hold'):
            raise ValueError(f'Invalid binding mode for {name}: {bind}')
        if bind['mode'].startswith('gamepad_') and bind.get('button') not in TARGETS:
            raise ValueError(f'Invalid gamepad target for {name}')
        if bind['mode'] in ('tap', 'hold') and not bind.get('keys'):
            raise ValueError(f'Missing keys for {name}')
        if bind['mode'].startswith('mouse_') and bind.get('button') not in ('left', 'right', 'middle'):
            raise ValueError(f'Invalid mouse button for {name}')


def main():
    global config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controls', help='Optional receiver controls Python file')
    parser.add_argument('--sender-ip', '--deck-ip', dest='deck_ip', required=True, help='Only accept packets from this sender IPv4 address')
    parser.add_argument('--port', type=int, default=50505)
    parser.add_argument('--token', default='CHANGE_THIS_PRIVATE_TOKEN')
    parser.add_argument('--debug-axes', action='store_true', help='Print incoming axes every 250ms')
    args = parser.parse_args()
    if args.controls:
        import runpy
        from types import SimpleNamespace
        config = SimpleNamespace(**runpy.run_path(args.controls))
    try:
        import pydirectinput
    except ImportError:
        sys.exit('Install Windows dependency: py -m pip install pydirectinput')
    pydirectinput.PAUSE = 0
    run_receiver(pydirectinput, args, 'Windows')


def run_receiver(input_api, args, platform_name, stop_event=None):
    """Shared authenticated transport/watchdog loop for Windows and macOS."""
    validate_config()
    bridge = InputBridge(input_api, debug_axes=args.debug_axes)
    link = ReceiverSession(bridge)
    print(f'EZDuoboxing v4.9.1 {platform_name} receiver: UDP {args.port}; accepting sender {args.deck_ip}', flush=True)
    print('Edit receiver_config.py and restart to change mappings.', flush=True)
    print(f'Keep the intended {platform_name} application focused.', flush=True)
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
                    server.bind(('0.0.0.0', args.port))
                    server.settimeout(0.008)
                    last_tick = time.monotonic()
                    while stop_event is None or not stop_event.is_set():
                        try:
                            packet, addr = server.recvfrom(2048)
                        except socket.timeout:
                            packet, addr = None, None
                        now = time.monotonic()
                        # Check timeout before applying a newly arrived state.
                        link.tick(now)
                        if packet is not None and addr[0] == args.deck_ip:
                            message = decode_packet(packet, args.token)
                            if message is not None:
                                link.accept(message, now)
                        dt = min(now - last_tick, 0.04)
                        last_tick = now
                        bridge.tick(now, max(0.0, dt))
            except OSError as exc:
                link.disconnect()
                print(f'UDP receiver error: {exc}; reopening in 1 second.', flush=True)
                time.sleep(1.0)
    finally:
        bridge.release_all()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.')
