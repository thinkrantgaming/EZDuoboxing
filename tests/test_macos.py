"""macOS backend tests use fake Quartz events; never type or move the real pointer."""
import types
import unittest
from unittest import mock

import macos_receiver as mac
import windows_receiver as core
from test_bridge import ZERO


class FakeQuartz:
    kCGEventSourceStatePrivate = -1
    kCGHIDEventTap = 0
    kCGEventFlagMaskShift = 2
    kCGEventFlagMaskControl = 4
    kCGEventFlagMaskAlternate = 8
    kCGEventFlagMaskCommand = 16
    kCGMouseButtonLeft, kCGMouseButtonRight, kCGMouseButtonCenter = 0, 1, 2
    kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGEventLeftMouseDragged = 1, 2, 6
    kCGEventRightMouseDown, kCGEventRightMouseUp, kCGEventRightMouseDragged = 3, 4, 7
    kCGEventOtherMouseDown, kCGEventOtherMouseUp, kCGEventOtherMouseDragged = 25, 26, 27
    kCGEventMouseMoved = 5
    kCGMouseEventDeltaX, kCGMouseEventDeltaY, kCGMouseEventClickState = 4, 5, 1

    def __init__(self):
        self.events = []

    def CGEventSourceCreate(self, state):
        return object()

    def CGEventCreateKeyboardEvent(self, source, code, down):
        return dict(kind='key', code=code, down=down)

    def CGEventCreateMouseEvent(self, source, typ, position, button):
        return dict(kind='mouse', type=typ, position=position, button=button, fields={})

    def CGEventCreate(self, source):
        return object()

    def CGEventGetLocation(self, event):
        return types.SimpleNamespace(x=100, y=200)

    def CGEventSetIntegerValueField(self, event, field, value):
        event['fields'][field] = value

    def CGEventSetFlags(self, event, flags):
        event['flags'] = flags

    def CGEventPost(self, tap, event):
        self.events.append(event)

    def CGPreflightPostEventAccess(self):
        return True


class MacTests(unittest.TestCase):
    def setUp(self):
        self.q = FakeQuartz()
        self.api = mac.MacInput(self.q)
        self.bridge = core.InputBridge(self.api)
        self.link = core.ReceiverSession(self.bridge)

    def test_shift_chord_has_flags_on_number_and_releases_in_reverse(self):
        with mock.patch.dict(core.config.BINDINGS, {'A': {'mode': 'tap', 'keys': ['shift', '1']}}):
            self.bridge.update_state(['A'], ZERO, 1)
            self.bridge.tick(2, 0)
        self.assertEqual([(e['code'], e['down'], e['flags']) for e in self.q.events],
                         [(56, True, 2), (18, True, 2), (18, False, 2), (56, False, 0)])
        self.assertFalse(self.api.keys)

    def test_two_buttons_share_shift_until_last_release(self):
        with mock.patch.dict(core.config.BINDINGS, {
            'LT': {'mode': 'hold', 'keys': ['shift']},
            'RT': {'mode': 'hold', 'keys': ['shift']},
        }):
            self.bridge.update_state(['LT', 'RT'], ZERO, 1)
            self.bridge.update_state(['RT'], ZERO, 2)
            self.assertEqual(len(self.q.events), 1)
            self.bridge.release_all()
        self.assertEqual(len(self.q.events), 2)
        self.assertFalse(self.api.keys)

    def test_aliases_and_both_sides_do_not_release_held_modifier_early(self):
        self.api.keyDown('ctrl')
        self.api.keyDown('control')
        self.api.keyUp('ctrl')
        self.assertEqual(len(self.q.events), 1)
        self.api.keyDown('ctrlright')
        self.api.keyUp('control')
        self.assertEqual(self.q.events[-1]['flags'], 4)
        self.api.keyUp('ctrlright')
        self.assertEqual(self.q.events[-1]['flags'], 0)

    def test_option_command_and_arrow(self):
        self.api.keyDown('option')
        self.api.keyDown('cmd')
        self.api.keyDown('left')
        self.assertEqual(self.q.events[-1]['code'], 123)
        self.assertEqual(self.q.events[-1]['flags'], 24)

    def test_each_mouse_button_click_and_drag_preserves_modifier(self):
        for button, drag in [('left', 6), ('right', 7), ('middle', 27)]:
            self.api.keyDown('shift')
            self.api.mouseDown(button)
            self.api.moveRel(4, -5)
            event = self.q.events[-1]
            self.assertEqual((event['type'], event['position'], event['flags']), (drag, (104, 195), 2))
            self.assertEqual(event['fields'][self.q.kCGMouseEventDeltaX], 4)
            self.assertEqual(event['fields'][self.q.kCGMouseEventDeltaY], -5)
            self.api.mouseUp(button)
            self.assertEqual(self.q.events[-1]['fields'][self.q.kCGMouseEventClickState], 1)
            self.api.keyUp('shift')
        self.assertFalse(self.api.mouse_buttons)
        self.api.moveRel(1, 2)
        self.assertEqual(self.q.events[-1]['type'], self.q.kCGEventMouseMoved)

    def test_route_release_and_timeout_clear_movement_modifier_mouse_and_taps(self):
        for timeout in (False, True):
            msg = dict(session='s', seq=10 if timeout else 1, buttons=['B', 'X', 'LB'],
                       axes={**ZERO, 'LX': -1}, healer_active=True)
            with mock.patch.dict(core.config.BINDINGS, {'LB': {'mode': 'mouse_hold', 'button': 'left'}}):
                self.link.accept(msg, 1)
                self.assertTrue(self.api.keys)
                self.assertTrue(self.api.mouse_buttons)
                if timeout:
                    self.link.tick(3)
                else:
                    self.link.accept({**msg, 'seq': 2, 'healer_active': False}, 1.01)
                self.assertFalse(self.api.keys)
                self.assertFalse(self.api.mouse_buttons)
                self.assertFalse(self.bridge.pending_taps)

    def test_all_default_bindings_supported_and_unsupported_key_fails_early(self):
        mac.validate_mac_bindings(core.config)
        with mock.patch.dict(core.config.BINDINGS, {'A': {'mode': 'tap', 'keys': ['volumeup']}}):
            with self.assertRaisesRegex(ValueError, 'A: Unsupported macOS key'):
                mac.validate_mac_bindings(core.config)
        with self.assertRaises(ValueError): mac.key_code('!')

    def test_permission_denied_never_starts_network_or_posts_events(self):
        with mock.patch.object(mac.sys, 'platform', 'darwin'), \
             mock.patch('sys.argv', ['macos_receiver.py', '--deck-ip', '192.0.2.3']), \
             mock.patch.dict('sys.modules', {'Quartz': self.q}), \
             mock.patch.object(self.q, 'CGPreflightPostEventAccess', return_value=False), \
             mock.patch.object(core, 'run_receiver') as run:
            with self.assertRaisesRegex(SystemExit, 'Accessibility permission'):
                mac.main()
            run.assert_not_called()
        self.assertFalse(self.q.events)

    def test_mac_launch_uses_shared_receiver_without_windows_dependency(self):
        with mock.patch.object(mac.sys, 'platform', 'darwin'), \
             mock.patch('sys.argv', ['macos_receiver.py', '--deck-ip', '192.0.2.3', '--token', 'secret']), \
             mock.patch.dict('sys.modules', {'Quartz': self.q}), \
             mock.patch.object(core, 'run_receiver') as run:
            mac.main()
        api, args, label = run.call_args.args
        self.assertIsInstance(api, mac.MacInput)
        self.assertEqual((args.deck_ip, args.token, label), ('192.0.2.3', 'secret', 'macOS'))
        self.assertFalse(self.q.events)


if __name__ == '__main__':
    unittest.main()
