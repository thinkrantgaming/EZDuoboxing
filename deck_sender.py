#!/usr/bin/env python3
"""Steam Deck input -> authenticated UDP -> remote receivers.

Default virtual mode retains Steam Input's virtual Xbox mapping. Optional
--input-source native reads physical buttons/sticks independently of that layout.
Steam Input remains responsible for local bindings and remote-layer suppression.
Configure destination selection in config.py. No extra SteamOS Python packages.
"""
import argparse
import fcntl
import glob
import ipaddress
import os
import secrets
import selectors
import signal
import socket
import struct
import sys
import time
from pathlib import Path
from native_controls import NativeControls
from sender_common import (
    encode_packet, RetryingUDP, decode_native_grips, RouteSelector, load_hosts, normalize_native_report, native_disconnected, TouchpadDirections, touchpad_debug_line, neutral_snapshot, Destinations, NATIVE_GRIPS, NATIVE_PRODUCTS, AXIS_NAMES, FRAME_INTERVAL
)

# Linux x86_64 struct input_event. Steam Deck SteamOS runs x86_64.
INPUT_EVENT = struct.Struct('@llHHi')
ABS_INFO = struct.Struct('iiiiii')  # value, minimum, maximum, fuzz, flat, resolution
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, SYN_DROPPED = 0, 3
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0, 1, 2, 3, 4, 5
ABS_HAT0X, ABS_HAT0Y = 16, 17
BUTTON_CODES = {
    304: 'A', 305: 'B', 307: 'X', 308: 'Y',
    310: 'LB', 311: 'RB', 314: 'BACK', 315: 'START',
    317: 'L3', 318: 'R3',
    # On some devices triggers/D-pad also appear as digital buttons.
    312: 'LT', 313: 'RT',
    544: 'DPAD_UP', 545: 'DPAD_DOWN', 546: 'DPAD_LEFT', 547: 'DPAD_RIGHT',
}
STICKS = {ABS_X: 'LX', ABS_Y: 'LY', ABS_RX: 'RX', ABS_RY: 'RY'}
TRIGGERS = {ABS_Z: 'LT', ABS_RZ: 'RT'}
TRIGGER_PRESS, TRIGGER_RELEASE = 0.55, 0.40


def device_name(path):
    try:
        return (Path('/sys/class/input') / Path(path).name / 'device/name').read_text().strip()
    except OSError:
        return '<unknown>'


def is_gamepad(name):
    clean = name.casefold().replace(' ', '').replace('-', '')
    return ('xbox360pad' in clean or 'xboxone' in clean or 'xboxcontroller' in clean
            or 'steamvirtualgamepad' in clean)


def abs_info(fd, code):
    # Linux _IOR('E', 0x40 + code, sizeof(struct input_absinfo))
    request = (2 << 30) | (ABS_INFO.size << 16) | (ord('E') << 8) | (0x40 + code)
    try:
        return ABS_INFO.unpack(fcntl.ioctl(fd, request, bytes(ABS_INFO.size)))
    except OSError:
        return None


def normalized_axis(raw, info):
    if info is None:
        low, high = -32768, 32767  # Common Xbox virtual controller fallback.
    else:
        low, high = info[1], info[2]
    center = (low + high) / 2
    scale = (high - low) / 2
    return round(max(-1.0, min(1.0, (raw - center) / scale)), 4) if scale else 0.0


def normalized_trigger(raw, info):
    if info is None:
        low, high = 0, 255
    else:
        low, high = info[1], info[2]
    return round(max(0.0, min(1.0, (raw - low) / (high - low))), 4) if high > low else 0.0

class GamepadState:
    def __init__(self, fd):
        self.info = {code: abs_info(fd, code) for code in (*STICKS, *TRIGGERS, ABS_HAT0X, ABS_HAT0Y)}
        self.digital = set()
        self.hat = set()
        self.trigger_keys = set()
        self.analog_triggers = set()
        self.axes = {key: 0.0 for key in AXIS_NAMES}
        self.triggers = {'LT': 0.0, 'RT': 0.0}
        self.hat_xy = [0, 0]
        # Reconstruct all held input on attach, including reconnect mid-hold.
        for code, info in self.info.items():
            if info is not None:
                self.update(EV_ABS, code, info[0])
        size = 96  # KEY_MAX=0x2ff, inclusive.
        request = (2 << 30) | (size << 16) | (ord('E') << 8) | 0x18
        pressed = fcntl.ioctl(fd, request, bytes(size))
        for code in BUTTON_CODES:
            if pressed[code // 8] & (1 << (code % 8)):
                self.update(EV_KEY, code, 1)

    @property
    def buttons(self):
        return self.digital | self.hat | self.trigger_keys | self.analog_triggers

    def update(self, event_type, code, value):
        """Return (buttons_changed, axes_changed). Ignore key auto-repeat."""
        before = self.buttons
        axes_changed = False
        if event_type == EV_KEY and value in (0, 1) and code in BUTTON_CODES:
            name = BUTTON_CODES[code]
            dest = self.trigger_keys if name in ('LT', 'RT') else self.digital
            if value:
                dest.add(name)
            else:
                dest.discard(name)
        elif event_type == EV_ABS:
            if code in STICKS:
                name = STICKS[code]
                new = normalized_axis(value, self.info[code])
                axes_changed = self.axes[name] != new
                self.axes[name] = new
            elif code in (ABS_HAT0X, ABS_HAT0Y):
                i = 0 if code == ABS_HAT0X else 1
                self.hat_xy[i] = value
                self.hat.clear()
                x, y = self.hat_xy
                if x < 0: self.hat.add('DPAD_LEFT')
                if x > 0: self.hat.add('DPAD_RIGHT')
                if y < 0: self.hat.add('DPAD_UP')
                if y > 0: self.hat.add('DPAD_DOWN')
            elif code in TRIGGERS:
                name = TRIGGERS[code]
                level = normalized_trigger(value, self.info[code])
                self.triggers[name] = level
                if level >= TRIGGER_PRESS:
                    self.analog_triggers.add(name)
                elif level <= TRIGGER_RELEASE:
                    self.analog_triggers.discard(name)
        return before != self.buttons, axes_changed

    def snapshot(self):
        return {'buttons': sorted(self.buttons), 'axes': self.axes.copy()}






def decode_grips(report):
    """Compatibility helper for the original R5-only mapping."""
    buttons = decode_native_grips(report)
    if buttons is None:
        return None
    return buttons - {'R5'} if 'R5' in buttons else set()




# Native layouts and device IDs documented by SDL's Steam Triton driver.
# See docs/ARCHITECTURE.md for upstream protocol references.


def hidraw_info(path):
    try:
        text = (Path('/sys/class/hidraw') / Path(path).name / 'device/uevent').read_text()
        info = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
        bus, vendor, product = (int(part, 16) for part in info['HID_ID'].split(':'))
        return bus, vendor, product, info.get('HID_NAME', '<unknown>')
    except (OSError, ValueError, KeyError):
        return None


def native_hidraw_paths(controller='deck'):
    for path in sorted(glob.glob('/dev/hidraw*')):
        info = hidraw_info(path)
        if info and info[1] == 0x28de and info[2] in NATIVE_PRODUCTS[controller]:
            yield path


def deck_hidraw_paths():
    # Retained for callers using the original Deck-only discovery API.
    yield from native_hidraw_paths('deck')




def gamepad_choices(device=None, strict=False):
    if device:
        return [device]
    choices = [path for path in sorted(glob.glob('/dev/input/event*')) if is_gamepad(device_name(path))]
    if strict and len(choices) > 1:
        print('Multiple virtual gamepads: use --device to select the Steam Controller output: '
              + ', '.join(choices), flush=True)
        return []
    return choices



class GripReader:
    """Read-only native routing and grips. Missing reports disable forwarding."""
    def __init__(self, enabled=False, path=None, touchpads='off', debug_touchpads=False, routes=None, controller='deck', debug_native=False):
        self.enabled, self.path = enabled, path
        self.controller = controller
        self.debug_native = debug_native
        self.last_native_debug = {}
        self.router = RouteSelector(routes or {'host1': 'R5'})
        self.touchpads = TouchpadDirections(touchpads)
        self.debug_touchpads = debug_touchpads
        self.last_pad_debug = 0.0
        self.pad_buttons = set()
        self.fds = {}
        self.buttons = set()
        self.r5 = False
        self.last_report = 0.0
        self.next_scan = 0.0
        self.active_fd = None
        self.warned = False
        self.physical = NativeControls(controller)

    def close(self):
        for fd in self.fds:
            os.close(fd)
        self.fds.clear()
        self.physical = NativeControls(self.controller)
        self.active_fd = None
        self.router.reset()
        self.buttons.clear()
        self.r5 = False
        self.pad_buttons.clear()
        self.touchpads.clear()

    def active_host(self, now):
        if self.active_fd is not None and now - self.last_report <= 0.5:
            return self.router.active
        self.router.reset()
        return None

    def held_r5(self, now):
        return self.active_fd is not None and self.r5 and now - self.last_report <= 0.5

    def poll(self, now, on_change=None):
        before = (self.router.active, self.r5, self.buttons.copy(), self.pad_buttons.copy())
        if not self.enabled:
            return False
        if not self.fds and now >= self.next_scan:
            self.next_scan = now + 2.0
            for path in ([self.path] if self.path else native_hidraw_paths(self.controller)):
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                    self.fds[fd] = path
                except OSError as exc:
                    if not self.warned:
                        print(f'Cannot read native grip from {path}: {exc}', flush=True)
            if not self.fds and not self.warned:
                print(f'No readable {self.controller} native device; ALL forwarding disabled, retrying.', flush=True)
                self.warned = True
            self.last_report = now
        for fd in list(self.fds):
            try:
                # Bound work so a busy controller cannot starve network heartbeats.
                for _ in range(64):
                    report = os.read(fd, 64)
                    if not report:
                        raise OSError('controller disconnected')
                    if self.debug_native and now - self.last_native_debug.get(fd, -10) >= 1.0:
                        print(f'NATIVE {self.controller} {self.fds[fd]} bytes={len(report)} hex={report.hex()}', flush=True)
                        self.last_native_debug[fd] = now
                    if native_disconnected(report, self.controller) and self.active_fd == fd:
                        self.router.reset()
                        self.buttons.clear()
                        self.r5 = False
                        self.pad_buttons.clear()
                        self.touchpads.clear()
                        self.active_fd = None
                        self.physical = NativeControls(self.controller)
                        print('Steam Controller wireless disconnect: releasing remote inputs.', flush=True)
                        if on_change is not None:
                            on_change()
                        continue
                    raw_report = report
                    report = normalize_native_report(report, self.controller)
                    if report is None:
                        continue
                    buttons = decode_native_grips(report)
                    if buttons is not None and self.active_fd in (None, fd):
                        if self.active_fd is None:
                            print(f'Native grips attached ({self.controller}): {self.fds[fd]}', flush=True)
                        self.active_fd = fd
                        physical_changed = self.physical.update(raw_report)
                        r5 = 'R5' in buttons
                        previous = self.router.active
                        selected = self.router.update(buttons | self.physical.buttons)
                        if previous != selected:
                            self.touchpads.clear()
                            print(f'Route: {selected or "local / waiting for selectors to release"}', flush=True)
                        buttons = buttons - {self.router.routes[selected]} if selected else set()
                        pads = self.touchpads.update(report, active=selected is not None)
                        changed = (physical_changed or previous != selected or self.buttons != buttons
                                   or self.r5 != r5 or self.pad_buttons != pads)
                        self.pad_buttons = pads
                        if self.debug_touchpads and (changed or now - self.last_pad_debug >= 0.1):
                            print(touchpad_debug_line(report, pads), flush=True)
                            self.last_pad_debug = now
                        self.r5 = r5
                        self.buttons = buttons
                        self.last_report = now
                        if changed and on_change is not None:
                            on_change()
                        self.last_report = now
                        self.warned = False
            except BlockingIOError:
                pass
            except OSError:
                os.close(fd)
                del self.fds[fd]
                if self.active_fd == fd:
                    self.active_fd = None
                    self.router.reset()
                    self.physical = NativeControls(self.controller)
                    self.buttons.clear()
                    self.r5 = False
                    self.pad_buttons.clear()
                    self.touchpads.clear()
        if self.fds and now - self.last_report > 0.5:
            if not self.warned:
                print('Native grip reports stopped; disabling ALL forwarding and rescanning.', flush=True)
                self.warned = True
            self.close()
            self.next_scan = now + 2.0
        return before != (self.router.active, self.r5, self.buttons, self.pad_buttons)


def gated_snapshot(state, native, now, include_grips=False, include_pads=False):
    if not native.held_r5(now):
        return {'buttons': [], 'axes': dict.fromkeys(AXIS_NAMES, 0.0),
                'healer_active': False}
    snapshot = state.snapshot() if state else {'buttons': [], 'axes': dict.fromkeys(AXIS_NAMES, 0.0)}
    if include_grips:
        snapshot['buttons'] = sorted(set(snapshot['buttons']) | native.buttons)
    if include_pads:
        snapshot['buttons'] = sorted(set(snapshot['buttons']) | native.pad_buttons)
    snapshot['healer_active'] = True
    return snapshot


def routed_snapshots(state, native, now, hosts, include_grips=True, include_pads=True):
    active = native.active_host(now)
    snapshots = {name: neutral_snapshot() for name in hosts}
    # Losing the virtual device disables native actions too, until it reattaches.
    if active in snapshots and state is not None:
        snapshot = state.snapshot()
        buttons = set(snapshot['buttons'])
        if include_grips:
            buttons |= native.buttons
        if include_pads:
            buttons |= native.pad_buttons
        buttons.discard(hosts[active]['button'])
        snapshot['buttons'] = sorted(buttons)
        snapshot['healer_active'] = True  # Keep wire v4 compatible.
        snapshots[active] = snapshot
    return snapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('windows_ip', nargs='?', help='Legacy single-host IP; omit to use config.py')
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('config.py'),
                        help='Deck host/routing configuration (used when WINDOWS_IP is omitted)')
    parser.add_argument('--port', type=int, default=50505, help='Port for legacy single-host mode')
    parser.add_argument('--token', help='Override token for all destinations')
    parser.add_argument('--controller', choices=('deck', 'steam'), default='deck',
                        help='Native hardware: deck (default), or Steam Controller 2026 over USB/Bluetooth/puck')
    parser.add_argument('--input-source', choices=('virtual', 'native'), default=None,
                        help='native reads physical controls independently of Steam Input')
    parser.add_argument('--debug-native', action='store_true', help='Print sampled native report bytes for troubleshooting')
    parser.add_argument('--device', help='Override input device, e.g. /dev/input/event12')
    parser.add_argument('--list', action='store_true', help='Show names/readability of input devices')
    parser.add_argument('--touchpads', nargs='?', const='pressure', default=None,
                        choices=('off', 'pressure', 'click', 'touch'),
                        help='Native pad directions: pressure (default), click bit, or touch')
    parser.add_argument('--pad-press-pressure', type=int, default=2500)
    parser.add_argument('--pad-release-pressure', type=int, default=1800)
    parser.add_argument('--debug-touchpads', action='store_true',
                        help='Log native pad coordinates, touch, click and pressure')
    parser.add_argument('--grips', action='store_true', default=None, help='Forward native action grips')
    parser.add_argument('--no-grips', dest='grips', action='store_false', help='Disable action grips; routing still works')
    parser.add_argument('--grip-device', help='Optional /dev/hidrawN override; implies --grips')
    parser.add_argument('--probe', action='store_true', help='Print button/axis activity; send no packets')
    args = parser.parse_args()
    if not 0 <= args.pad_release_pressure < args.pad_press_pressure <= 65535:
        parser.error('Pad pressure thresholds must be 0 <= release < press <= 65535')
    if args.list:
        for path in sorted(glob.glob('/dev/input/event*')):
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                os.close(fd)
                status = 'readable'
            except OSError as exc:
                status = f'unreadable: {exc}'
            print(f'{path} | {device_name(path)} | {status}')
        for kind in NATIVE_PRODUCTS:
            for path in native_hidraw_paths(kind):
                info = hidraw_info(path)
                if info is None:
                    continue  # Device may disappear while listing it.
                bus, vendor, product, name = info
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                    os.close(fd)
                    status = 'readable'
                except OSError as exc:
                    status = f'unreadable: {exc}'
                print(f'{path} | {kind} {vendor:04x}:{product:04x} bus={bus:04x} {name} | {status}')
        return

    try:
        if args.windows_ip:
            ip = str(ipaddress.IPv4Address(args.windows_ip))
            if not 1 <= args.port <= 65535:
                raise ValueError('Port must be between 1 and 65535')
            hosts = {'host1': dict(ip=ip, port=args.port, button='R5',
                                  token=args.token or 'CHANGE_THIS_PRIVATE_TOKEN')}
            settings = {}  # Preserve the original single-host command's defaults.
        else:
            hosts, settings = load_hosts(args.config, probe=args.probe)
        if args.token is not None:
            if not args.token:
                raise ValueError('Token cannot be empty')
            for host in hosts.values():
                host['token'] = args.token
        args.input_source = args.input_source or settings.get('INPUT_SOURCE', 'virtual')
        if args.input_source not in ('virtual', 'native'): raise ValueError('INPUT_SOURCE must be virtual or native')
        if args.grips is None:
            args.grips = settings.get('GRIPS', False)
        if type(args.grips) is not bool:
            raise ValueError('GRIPS must be True or False')
        args.touchpads = args.touchpads or settings.get('TOUCHPADS', 'off')
        if args.touchpads not in ('off', 'pressure', 'click', 'touch'):
            raise ValueError('TOUCHPADS must be off, pressure, click, or touch')
    except (OSError, ValueError, SyntaxError) as exc:
        parser.error(str(exc))

    session = secrets.token_hex(8)
    sequence = 0
    selector = selectors.DefaultSelector()
    destinations = None if args.probe else Destinations(hosts)
    grips = GripReader(True, args.grip_device, args.touchpads, args.debug_touchpads,
                       routes={name: h['button'] for name, h in hosts.items()},
                       controller=args.controller, debug_native=args.debug_native)
    grips.touchpads.press_pressure = args.pad_press_pressure
    grips.touchpads.release_pressure = args.pad_release_pressure
    include_grips = args.grips or bool(args.grip_device)
    device_fd, device_path, state = None, None, None
    last_sent, last_scan, last_axis_print = 0.0, 0.0, 0.0
    old_buttons = {name: set() for name in hosts}
    dropped = False

    def send(force=False):
        nonlocal sequence, last_sent, old_buttons, last_axis_print
        now = time.monotonic()
        if not force and now - last_sent < FRAME_INTERVAL:
            return
        snapshots = routed_snapshots(grips.physical if args.input_source == 'native' else state, grips, now, hosts, include_grips, args.touchpads != 'off')
        sequence += 1
        if args.probe:
            for name, snapshot in snapshots.items():
                current = set(snapshot['buttons'])
                for button in sorted(current - old_buttons[name]):
                    print(f'{name}: {button} down', flush=True)
                for button in sorted(old_buttons[name] - current):
                    print(f'{name}: {button} up', flush=True)
                old_buttons[name] = current
                if now - last_axis_print >= 0.2 and any(abs(v) > 0.12 for v in snapshot['axes'].values()):
                    print(name + ' STICKS  ' + ' '.join(f'{k}={v:+.2f}' for k, v in snapshot['axes'].items()), flush=True)
                    last_axis_print = now
        else:
            destinations.send(snapshots, session, sequence, now)
        last_sent = now

    print('EZDuoboxing v4.9.1 Deck sender (configurable host routing).', flush=True)
    print('Probe mode: no network sending.' if args.probe else 'Destinations ready.', flush=True)
    print(f'Input source: {args.input_source}; native hardware: {args.controller}', flush=True)
    for name, host in hosts.items():
        print(f"{host['button']} -> {name} ({host['ip']}:{host['port']})", flush=True)
    try:
        while True:
            now = time.monotonic()
            if grips.poll(now, lambda: send(force=True)):
                send(force=True)
            if args.input_source == 'virtual' and device_fd is None and now - last_scan >= 1.5:
                last_scan = now
                choices = gamepad_choices(args.device, strict=args.controller == 'steam')
                for path in choices:
                    name = device_name(path)
                    if not args.device and not is_gamepad(name):
                        continue
                    fd = None
                    try:
                        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                        new_state = GamepadState(fd)
                        selector.register(fd, selectors.EVENT_READ)
                    except OSError as exc:
                        if fd is not None:
                            os.close(fd)
                        print(f'Unable to attach {path} ({name}): {exc}', file=sys.stderr, flush=True)
                        continue
                    device_fd, device_path, state = fd, path, new_state
                    dropped = False
                    print(f'Attached: {path} ({name})', flush=True)
                    send(force=True)
                    break
                if device_fd is None:
                    print('Waiting for virtual Xbox controller; try --list.', flush=True)

            for _key, _mask in selector.select(timeout=0.015):
                try:
                    data = os.read(device_fd, INPUT_EVENT.size * 128)
                except BlockingIOError:
                    continue
                except OSError:
                    data = b''
                if not data:
                    print('Input device disconnected; releasing remote inputs.', flush=True)
                    selector.unregister(device_fd)
                    os.close(device_fd)
                    device_fd, device_path, state = None, None, None
                    send(force=True)
                    last_scan = 0.0
                    continue
                for i in range(0, len(data) - INPUT_EVENT.size + 1, INPUT_EVENT.size):
                    _, _, typ, code, value = INPUT_EVENT.unpack_from(data, i)
                    if typ == EV_SYN and code == SYN_DROPPED:
                        dropped = True
                        state = None
                        send(force=True)
                        continue
                    if dropped:
                        if typ == EV_SYN and code == SYN_REPORT:
                            try:
                                state = GamepadState(device_fd)
                                dropped = False
                            except OSError:
                                selector.unregister(device_fd)
                                os.close(device_fd)
                                device_fd, device_path, state = None, None, None
                                last_scan = 0.0
                                break
                            send(force=True)
                        continue
                    buttons_changed, _axes_changed = state.update(typ, code, value)
                    if buttons_changed:
                        send(force=True)  # Don't miss very brief button taps.
            send()  # Continuous axes + heartbeat even if not receiving events.
    except KeyboardInterrupt:
        print('\nStopping sender.', flush=True)
    finally:
        # Final empty snapshot: receiver also has a watchdog in case this is lost.
        state = None
        grips.close()
        try: send(force=True)
        except OSError: pass
        if device_fd is not None:
            try: selector.unregister(device_fd)
            except Exception: pass
            os.close(device_fd)
        selector.close()
        if destinations is not None:
            destinations.close()


if __name__ == '__main__':
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    main()
