#!/usr/bin/env python3
"""Steam Controller (2026) on Windows -> authenticated UDP -> remote receivers.

Uses native HID input; Steam Input remains responsible for LOCAL game bindings.
No HID feature writes, virtual-controller drivers or local key injection.
"""
import argparse
import ipaddress
import secrets
import signal
import struct
import sys
import time
from pathlib import Path

from sender_common import (
    AXIS_NAMES, FRAME_INTERVAL, NATIVE_PRODUCTS, RouteSelector, TouchpadDirections,
    Destinations, load_hosts, neutral_snapshot, normalize_native_report,
    decode_native_grips, native_disconnected, touchpad_debug_line,
)

BUTTON_BITS = {
    0: 'A', 1: 'B', 2: 'X', 3: 'Y', 5: 'R3', 6: 'START',
    9: 'RB', 10: 'DPAD_DOWN', 11: 'DPAD_RIGHT', 12: 'DPAD_LEFT',
    13: 'DPAD_UP', 14: 'BACK', 15: 'L3', 19: 'LB',
}


class ControllerState:
    def __init__(self, hosts, touchpads='pressure', grips=True, press_pressure=2500, release_pressure=1800):
        self.hosts = hosts
        self.router = RouteSelector({n: h['button'] for n, h in hosts.items()})
        self.pads = TouchpadDirections(touchpads, press_pressure=press_pressure, release_pressure=release_pressure)
        self.include_grips = grips
        self.triggers = set()
        self.buttons = set()
        self.axes = dict.fromkeys(AXIS_NAMES, 0.0)
        self.valid = False
        self.last_report = 0.0
        self.last_normalized = None
        self.reset()

    def reset(self):
        self.router.reset()  # Confirm selectors up before forwarding on attach/reconnect.
        self.pads.clear()
        self.triggers.clear()
        self.buttons.clear()
        self.axes = dict.fromkeys(AXIS_NAMES, 0.0)
        self.valid = False
        self.last_normalized = None

    def update(self, raw, now):
        normalized = normalize_native_report(raw, 'steam')
        if normalized is None:
            return False
        previous = (self.router.active, self.buttons.copy())
        grips = decode_native_grips(normalized)
        bits = struct.unpack_from('<I', raw, 2)[0]
        buttons = {name for bit, name in BUTTON_BITS.items() if bits & (1 << bit)}
        for name, value in zip(('LT', 'RT'), struct.unpack_from('<hh', raw, 6)):
            level = max(0.0, min(1.0, value / 32767.0))
            if level >= 0.55:
                self.triggers.add(name)
            elif level <= 0.40:
                self.triggers.discard(name)
        buttons |= self.triggers
        self.router.update(grips | buttons)
        if previous[0] != self.router.active:
            self.pads.clear()
        if self.include_grips:
            buttons |= grips
        buttons |= self.pads.update(normalized, active=self.router.active is not None)
        if self.router.active is not None:
            buttons.discard(self.hosts[self.router.active]['button'])
        self.buttons = buttons
        values = struct.unpack_from('<hhhh', raw, 10)
        self.axes = {name: round(max(-1.0, min(1.0, value / 32767.0)) * (-1 if name.endswith('Y') else 1), 4)
                     for name, value in zip(AXIS_NAMES, values)}
        self.last_report = now
        self.last_normalized = normalized
        self.valid = True
        return previous != (self.router.active, self.buttons)

    def snapshots(self, now):
        if self.valid and now - self.last_report > 0.5:
            self.reset()
        result = {name: neutral_snapshot() for name in self.hosts}
        if self.valid and self.router.active is not None:
            result[self.router.active] = dict(buttons=sorted(self.buttons), axes=self.axes.copy(), healer_active=True)
        return result


def devices(hid):
    return [d for d in hid.enumerate(0x28de, 0)
            if d['product_id'] in NATIVE_PRODUCTS['steam']]


class HidReader:
    """Nonblocking read-only use of HIDAPI, with per-path retry and stale release."""
    def __init__(self, hid, state, path=None, debug=False, debug_pads=False):
        self.hid, self.state, self.path = hid, state, path
        self.debug, self.debug_pads = debug, debug_pads
        self.handles = {}
        self.active = None
        self.next_scan = 0.0
        self.opened_at = 0.0
        self.last_debug = {}

    def close(self):
        for handle in self.handles.values():
            try:
                handle.close()
            except OSError:
                pass
        self.handles.clear()
        self.active = None
        self.state.reset()

    def scan(self, now):
        self.next_scan = now + 2.0
        try:
            found = devices(self.hid)
        except OSError as exc:
            print(f'HID enumeration failed: {exc}; retrying.', flush=True)
            return
        for item in found:
            path = item['path']
            if self.path is not None and path != self.path:
                continue
            if path in self.handles:
                continue
            handle = None
            try:
                handle = self.hid.device()
                handle.open_path(path)
                handle.set_nonblocking(1)
                self.handles[path] = handle
            except OSError as exc:
                if handle is not None:
                    try: handle.close()
                    except OSError: pass
                print(f'Cannot read HID {path!r}: {exc}', flush=True)
        self.opened_at = now
        if not self.handles:
            print('No readable Steam Controller (2026); retrying. Check --list.', flush=True)

    def poll(self, now, on_change):
        if not self.handles and now >= self.next_scan:
            self.scan(now)
        for path, handle in list(self.handles.items()):
            try:
                for _ in range(64):
                    raw = bytes(handle.read(64))
                    if not raw:
                        break  # Nonblocking read: no new report, not necessarily disconnected.
                    if self.debug and now - self.last_debug.get(path, -10) >= 1:
                        print(f'HID {path!r} bytes={len(raw)} hex={raw.hex()}', flush=True)
                        self.last_debug[path] = now
                    if native_disconnected(raw, 'steam') and self.active == path:
                        self.state.reset()
                        self.active = None
                        print('Controller disconnected: released remote inputs.', flush=True)
                        on_change()
                        continue
                    if normalize_native_report(raw, 'steam') is None or self.active not in (None, path):
                        continue
                    if self.active is None:
                        self.active = path
                        print(f'Native input attached: {path!r}. Release selectors, then choose a host.', flush=True)
                    old_route = self.state.router.active
                    changed = self.state.update(raw, now)
                    if old_route != self.state.router.active:
                        print(f'Route: {self.state.router.active or "local / release selectors"}', flush=True)
                    if self.debug_pads and (changed or now - self.last_debug.get('pads', -10) >= 0.1):
                        print(touchpad_debug_line(self.state.last_normalized, self.state.buttons), flush=True)
                        self.last_debug['pads'] = now
                    if changed:
                        on_change()
            except OSError as exc:
                print(f'HID read failed: {exc}; retrying.', flush=True)
                try: handle.close()
                except OSError: pass
                self.handles.pop(path, None)
                if self.active == path:
                    self.active = None
                    self.state.reset()
                    on_change()
        # Unsupported interfaces/status packets cannot keep held remote input alive.
        reference = self.state.last_report if self.state.valid else self.opened_at
        if self.handles and now - reference > (0.5 if self.state.valid else 2.0):
            print('No current controller state: releasing inputs and rescanning.', flush=True)
            self.close()
            self.next_scan = now + 1.0
            on_change()


class Output:
    def __init__(self, hosts, probe=False):
        self.session = secrets.token_hex(8)
        self.seq = 0
        self.destinations = None if probe else Destinations(hosts)
        self.previous = {n: neutral_snapshot() for n in hosts}
        self.last_axes = 0.0

    def send(self, snapshots, now):
        self.seq += 1
        if self.destinations is not None:
            self.destinations.send(snapshots, self.session, self.seq, now)
        else:
            for name, snapshot in snapshots.items():
                before, after = set(self.previous[name]['buttons']), set(snapshot['buttons'])
                for button in sorted(before - after): print(f'{name}: {button} up', flush=True)
                for button in sorted(after - before): print(f'{name}: {button} down', flush=True)
                if now - self.last_axes >= 0.2 and any(abs(v) > 0.12 for v in snapshot['axes'].values()):
                    print(name + ' STICKS ' + ' '.join(f'{k}={v:+.2f}' for k, v in snapshot['axes'].items()), flush=True)
                    self.last_axes = now
        self.previous = snapshots

    def close(self):
        if self.destinations is not None:
            self.destinations.close()


def run(hid, hosts, args, settings, stop_event=None):
    state = ControllerState(hosts, args.touchpads or settings.get('TOUCHPADS', 'pressure'),
                            settings.get('GRIPS', True), args.pad_press_pressure, args.pad_release_pressure)
    reader = HidReader(hid, state, args.hid_path.encode() if args.hid_path else None, args.debug_native, args.debug_touchpads)
    output = Output(hosts, args.probe)
    last_sent = -1.0
    def send():
        nonlocal last_sent
        now = time.monotonic()
        output.send(state.snapshots(now), now)
        last_sent = now
    print('EZDuoboxing v4.9.1 Windows sender — native Steam Controller input.', flush=True)
    print('PROBE: no network sending.' if args.probe else 'Sending to configured remote hosts.', flush=True)
    for name, host in hosts.items():
        print(f"{host['button']} -> {name} ({host['ip']}:{host['port']})", flush=True)
    try:
        while stop_event is None or not stop_event.is_set():
            reader.poll(time.monotonic(), send)
            if time.monotonic() - last_sent >= FRAME_INTERVAL:
                send()
            time.sleep(0.005)
    except KeyboardInterrupt:
        print('Stopping sender.', flush=True)
    finally:
        reader.close()
        try:
            send()
        finally:
            output.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receiver_ip', nargs='?', help='Optional single receiver IP, selected by R5')
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('config.py'))
    parser.add_argument('--port', type=int, default=50505, help='Port with single receiver IP')
    parser.add_argument('--token', help='Override destination token(s)')
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--list', action='store_true', help='List HID interfaces and paths; no network sending')
    parser.add_argument('--hid-path', help='Use one path from --list (quote the entire path)')
    parser.add_argument('--debug-native', action='store_true')
    parser.add_argument('--debug-touchpads', action='store_true')
    parser.add_argument('--touchpads', choices=('off', 'pressure', 'click', 'touch'))
    parser.add_argument('--pad-press-pressure', type=int, default=2500)
    parser.add_argument('--pad-release-pressure', type=int, default=1800)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Run this sender on Windows. Use deck_sender.py on SteamOS.')
    try:
        import hid
    except ImportError:
        parser.error('Install dependency: py -m pip install hidapi (package is hidapi, import is hid)')
    if not hasattr(hid, 'device'):
        parser.error('Wrong hid module installed; this sender needs the hidapi package.')
    if args.list:
        for item in devices(hid):
            print(f"{item['vendor_id']:04x}:{item['product_id']:04x} interface={item.get('interface_number')} "
                  f"usage_page={item.get('usage_page')} usage={item.get('usage')} {item.get('product_string')}")
            print('  path: ' + item['path'].decode(errors='replace'))
        return
    try:
        if args.receiver_ip:
            hosts = {'host1': dict(ip=str(ipaddress.IPv4Address(args.receiver_ip)), port=args.port,
                                  button='R5', token=args.token or 'CHANGE_THIS_PRIVATE_TOKEN')}
            settings = {}
        else:
            hosts, settings = load_hosts(args.config, probe=args.probe)
        if not 1 <= args.port <= 65535:
            raise ValueError('Port must be between 1 and 65535')
        if args.token is not None:
            if not args.token: raise ValueError('Token cannot be empty')
            for host in hosts.values(): host['token'] = args.token
        if type(settings.get('GRIPS', True)) is not bool:
            raise ValueError('GRIPS must be True or False')
        if (args.touchpads or settings.get('TOUCHPADS', 'pressure')) not in ('off', 'pressure', 'click', 'touch'):
            raise ValueError('Invalid TOUCHPADS mode')
        if not 0 <= args.pad_release_pressure < args.pad_press_pressure <= 65535:
            raise ValueError('Pressure thresholds must satisfy 0 <= release < press <= 65535')
    except (OSError, ValueError, SyntaxError) as exc:
        parser.error(str(exc))
    run(hid, hosts, args, settings)


if __name__ == '__main__':
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    main()
