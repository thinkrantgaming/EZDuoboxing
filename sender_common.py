"""Portable routing, wire protocol and native pad decoding shared by both senders."""
import hashlib
import hmac
import ipaddress
import json
import runpy
import socket
import struct

AXIS_NAMES = ('LX', 'LY', 'RX', 'RY')

FRAME_INTERVAL = 1 / 30  # Heartbeat + axes, 30 packets/second; button edges sent immediately.

def encode_packet(token, session, seq, snapshot):
    message = {'v': 4, 'session': session, 'seq': seq, **snapshot}
    body = json.dumps(message, separators=(',', ':'), sort_keys=True).encode('utf-8')
    signature = hmac.new(token.encode('utf-8'), body, hashlib.sha256).hexdigest().encode('ascii')
    return signature + b'|' + body

class RetryingUDP:
    """Retry local network errors; never queue old gameplay input."""
    def __init__(self, address, factory=socket.socket):
        self.address, self.factory = address, factory
        self.sock = None
        self.retry_at = 0.0
        self.failed = False

    def send(self, packet, now):
        if now < self.retry_at:
            return False
        try:
            if self.sock is None:
                self.sock = self.factory(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setblocking(False)
            self.sock.sendto(packet, self.address)
        except OSError as exc:
            self.close()
            self.retry_at = now + 1.0
            if not self.failed:
                print(f'UDP send failed: {exc}; retrying every second.', flush=True)
            self.failed = True
            return False
        if self.failed:
            print('UDP sending resumed (delivery is not acknowledged).', flush=True)
        self.failed = False
        return True

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

NATIVE_GRIPS = {'L4', 'L5', 'R4', 'R5'}
SELECTOR_BUTTONS = NATIVE_GRIPS | {'A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT',
    'BACK', 'START', 'L3', 'R3', 'DPAD_UP', 'DPAD_DOWN', 'DPAD_LEFT', 'DPAD_RIGHT'}

def decode_native_grips(report):
    """Decode physical buttons without assigning a routing role."""
    if len(report) != 64 or report[:3] != b'\x01\x00\x09':
        return None
    low, high = struct.unpack_from('<II', report, 8)
    return {name for name, active in (
        ('L4', high & 0x200), ('L5', low & 0x8000),
        ('R4', high & 0x400), ('R5', low & 0x10000)
    ) if active}

class RouteSelector:
    """First selector held wins; its release requires all selectors up to rearm."""
    def __init__(self, routes):
        self.routes = dict(routes)  # host name -> physical button
        self.active = None
        self.armed = True

    def reset(self):
        self.active = None
        self.armed = False  # After native loss, require a confirmed neutral report.

    def update(self, held):
        selected = [name for name, button in self.routes.items() if button in held]
        if self.active is not None:
            if self.routes[self.active] not in held:
                self.active = None
                self.armed = not selected
        elif not selected:
            self.armed = True
        elif self.armed:
            self.armed = False
            # Both in the same report are ambiguous; wait for both to be released.
            if len(selected) == 1:
                self.active = selected[0]
        return self.active

def load_hosts(path, probe=False):
    """Load trusted user configuration and reject ambiguous destinations."""
    settings = runpy.run_path(str(path))
    raw = settings.get('HOSTS')
    if not isinstance(raw, dict) or not raw:
        raise ValueError('config.py needs a nonempty HOSTS dictionary')
    hosts, buttons, endpoints = {}, set(), set()
    for name, item in raw.items():
        if not isinstance(name, str) or not name or not isinstance(item, dict):
            raise ValueError('Each HOSTS entry needs a name and a dictionary')
        if type(item.get('enabled', True)) is not bool:
            raise ValueError(f'{name}: enabled must be True or False')
        if not item.get('enabled', True):
            continue
        button = item.get('button')
        if not isinstance(button, str) or button not in SELECTOR_BUTTONS or button in buttons:
            raise ValueError(f'{name}: choose a unique selector from {sorted(SELECTOR_BUTTONS)}')
        ip, port = item.get('ip'), item.get('port', 50505)
        token = item.get('token', settings.get('TOKEN', 'CHANGE_THIS_PRIVATE_TOKEN'))
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError(f'{name}: port must be between 1 and 65535')
        if not isinstance(token, str) or not token:
            raise ValueError(f'{name}: token must be a nonempty string')
        if not probe:
            try:
                ip = str(ipaddress.IPv4Address(ip))
            except (ipaddress.AddressValueError, TypeError):
                raise ValueError(f'{name}: replace ip with the receiver IPv4 address') from None
            if (ip, port) in endpoints:
                raise ValueError(f'{name}: two hosts cannot use the same IP and port')
            endpoints.add((ip, port))
        buttons.add(button)
        hosts[name] = dict(ip=ip, port=port, token=token, button=button)
    if not hosts:
        raise ValueError('Enable at least one HOSTS entry')
    return hosts, settings

NATIVE_PRODUCTS = {'deck': {0x1205}, 'steam': {0x1302, 0x1303, 0x1304, 0x1305}}

def normalize_native_report(report, controller='deck'):
    """Convert supported grip/pad state to the established Deck decoder layout.

    Steam Input continues to supply the virtual Xbox buttons/axes. We do not
    synthesize those from native reports or change controller firmware settings.
    Triton 0x42/0x45 and timestamped 0x47 formats have at least 46 bytes.
    """
    if controller == 'deck':
        return report if len(report) == 64 and report[:3] == b'\x01\x00\x09' else None
    if controller != 'steam' or not 46 <= len(report) <= 64 or report[0] not in (0x42, 0x45, 0x47):
        return None
    buttons = struct.unpack_from('<I', report, 2)[0]
    low = high = 0
    for native_bit, deck_bit in ((8, 16), (18, 15), (25, 19), (21, 20), (26, 17), (22, 18)):
        if buttons & (1 << native_bit):
            low |= 1 << deck_bit
    if buttons & (1 << 17): high |= 0x200  # L4
    if buttons & (1 << 7): high |= 0x400   # R4
    offset = 20 if report[0] == 0x47 else 18
    lx, ly, lp, rx, ry, rp = struct.unpack_from('<hhHhhH', report, offset)
    converted = bytearray(64)
    converted[:4] = b'\x01\x00\x09\x40'
    struct.pack_into('<III', converted, 4, report[1], low, high)
    struct.pack_into('<hhhh', converted, 16, lx, ly, rx, ry)
    struct.pack_into('<HH', converted, 56, lp, rp)
    return bytes(converted)

def native_disconnected(report, controller):
    return (controller == 'steam' and len(report) >= 2
            and report[0] in (0x46, 0x79) and report[1] == 1)

class TouchpadDirections:
    """Settle directions before activating; debounce release and latch clicks."""
    def __init__(self, mode='off', settle_reports=3, press_pressure=2500, release_pressure=1800):
        if not 0 <= release_pressure < press_pressure <= 65535:
            raise ValueError('Pressure thresholds must be 0 <= release < press <= 65535')
        self.press_pressure = press_pressure
        self.release_pressure = release_pressure
        self.pressure_held = set()
        self.mode = mode
        self.settle_reports = settle_reports
        self.latched = {}
        self.pressed = set()
        self.candidates = {}
        self.counts = {}
        self.releases = {}

    def clear(self):
        self.pressure_held.clear()
        self.latched.clear()
        self.pressed.clear()
        self.candidates.clear()
        self.counts.clear()
        self.releases.clear()

    def reset_pad(self, name):
        self.pressure_held.discard(name)
        self.latched.pop(name, None)
        self.pressed.discard(name)
        self.candidates.pop(name, None)
        self.counts.pop(name, None)
        self.releases.pop(name, None)

    def update(self, report, active=None):
        low = struct.unpack_from('<I', report, 8)[0]
        if active is None:
            active = bool(low & 0x10000)  # Compatibility with R5-only callers.
        if self.mode == 'off' or not active:
            self.clear()
            return set()
        result = set()
        for name, offset, touch_bit, click_bit, pressure_offset in (
            ('LPAD', 16, 19, 17, 56), ('RPAD', 20, 20, 18, 58)
        ):
            touched = bool(low & (1 << touch_bit))
            clicked = bool(low & (1 << click_bit))
            if self.mode == 'pressure':
                pressure = struct.unpack_from('<H', report, pressure_offset)[0]
                if not touched or pressure <= self.release_pressure:
                    self.pressure_held.discard(name)
                elif pressure >= self.press_pressure:
                    self.pressure_held.add(name)
                active = touched and name in self.pressure_held
            else:
                active = touched and (clicked or self.mode == 'touch')
            x, y = struct.unpack_from('<hh', report, offset)
            direction = None
            if active and max(abs(x), abs(y)) >= 8192:
                direction = ('RIGHT' if x > 0 else 'LEFT') if abs(x) >= abs(y) else ('UP' if y > 0 else 'DOWN')
            if not active:
                self.releases[name] = self.releases.get(name, 0) + 1
                self.candidates.pop(name, None)
                self.counts.pop(name, None)
                if self.releases[name] >= self.settle_reports:
                    self.reset_pad(name)
            else:
                self.releases[name] = 0
                self.pressed.add(name)
                # Clicks keep the selected sector until a settled release.
                # A center/invalid first report does not permanently swallow the press.
                if self.mode not in ('click', 'pressure') or name not in self.latched:
                    if self.candidates.get(name) == direction:
                        self.counts[name] = self.counts.get(name, 0) + 1
                    else:
                        self.candidates[name] = direction
                        self.counts[name] = 1
                    if self.counts[name] >= self.settle_reports:
                        if direction is None:
                            self.latched.pop(name, None)
                        else:
                            self.latched[name] = direction
            if name in self.latched:
                result.add(name + '_' + self.latched[name])
        return result

def touchpad_debug_line(report, outputs):
    low = struct.unpack_from('<I', report, 8)[0]
    packet = struct.unpack_from('<I', report, 4)[0]
    fields = [f'PADRAW seq={packet} R5={int(bool(low & 0x10000))} L5={int(bool(low & 0x8000))}']
    for name, offset, touch_bit, click_bit, pressure_offset in (
        ('L', 16, 19, 17, 56), ('R', 20, 20, 18, 58)
    ):
        x, y = struct.unpack_from('<hh', report, offset)
        pressure = struct.unpack_from('<H', report, pressure_offset)[0]
        fields.append(f'{name}:touch={int(bool(low & (1 << touch_bit)))} '
                      f'click={int(bool(low & (1 << click_bit)))} '
                      f'x={x} y={y} pressure={pressure}')
    return ' | '.join(fields) + ' | output=' + (','.join(sorted(outputs)) or '-')

def neutral_snapshot():
    return {'buttons': [], 'axes': dict.fromkeys(AXIS_NAMES, 0.0), 'healer_active': False}

class Destinations:
    """Independent transports, neutral heartbeats to every unselected host."""
    def __init__(self, hosts):
        self.hosts = hosts
        self.transports = {name: RetryingUDP((h['ip'], h['port'])) for name, h in hosts.items()}

    def send(self, snapshots, session, sequence, now):
        # Send releases before the selected destination's state.
        for name in sorted(snapshots, key=lambda n: snapshots[n]['healer_active']):
            self.transports[name].send(
                encode_packet(self.hosts[name]['token'], session, sequence, snapshots[name]), now)

    def close(self):
        for transport in self.transports.values():
            transport.close()
