"""Logic-only tests. Runs on Linux, macOS or Windows: python3 test_bridge.py"""
import hashlib
import hmac
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deck_sender as sender
import windows_receiver as receiver
import receiver_config as config


class FakeAPI:
    def __init__(self): self.calls = []
    def keyDown(self, key): self.calls.append(('kd', key))
    def keyUp(self, key): self.calls.append(('ku', key))
    def mouseDown(self, button): self.calls.append(('md', button))
    def mouseUp(self, button): self.calls.append(('mu', button))
    def moveRel(self, dx, dy, relative=True, _pause=False):
        self.calls.append(('mv', dx, dy))


ZERO = dict.fromkeys(('LX', 'LY', 'RX', 'RY'), 0.0)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.b = receiver.InputBridge(self.api)

    def test_held_modifier_plus_simultaneous_key_chord(self):
        self.b.update_state(['B'], ZERO, 1.0)
        self.assertIn(('kd', 'shift'), self.api.calls)
        self.b.update_state(['B', 'X'], ZERO, 1.1)
        self.assertIn(('kd', '2'), self.api.calls)
        self.b.tick(1.2, 0.0)
        self.assertIn(('ku', '2'), self.api.calls)
        self.assertNotIn(('ku', 'shift'), self.api.calls)
        self.b.update_state([], ZERO, 1.3)
        self.assertEqual(self.api.calls.count(('ku', 'shift')), 1)
        self.assertEqual(self.b.refs, {})

    def test_very_short_press_produces_one_tap(self):
        self.b.update_state(['A'], ZERO, 1.0)
        self.b.update_state([], ZERO, 1.02)
        self.b.tick(1.07, 0.03)
        self.assertEqual(self.api.calls.count(('kd', '1')), 1)
        self.assertEqual(self.api.calls.count(('ku', '1')), 1)

    def test_dpad(self):
        self.b.update_state(['DPAD_UP', 'DPAD_LEFT'], ZERO, 1.0)
        self.assertIn(('kd', 'f1'), self.api.calls)
        self.assertIn(('kd', 'f3'), self.api.calls)
        self.b.tick(1.1, 0.016)
        self.assertIn(('ku', 'f1'), self.api.calls)
        self.assertIn(('ku', 'f3'), self.api.calls)

    def test_left_stick_diagonal_and_center(self):
        axes = {**ZERO, 'LX': -0.95, 'LY': -0.97}
        self.b.update_state([], axes, 1.0)
        self.assertIn(('kd', 'w'), self.api.calls)
        self.assertIn(('kd', 'a'), self.api.calls)
        self.b.update_state([], ZERO, 1.1)
        self.assertIn(('ku', 'w'), self.api.calls)
        self.assertIn(('ku', 'a'), self.api.calls)

    def test_movement_hysteresis(self):
        self.b.update_state([], {**ZERO, 'LY': -0.5}, 1.0)
        self.b.update_state([], {**ZERO, 'LY': -0.40}, 1.1)
        self.assertNotIn(('ku', 'w'), self.api.calls)
        self.b.update_state([], {**ZERO, 'LY': -0.30}, 1.2)
        self.assertIn(('ku', 'w'), self.api.calls)

    def test_right_stick_sustained_relative_mouse(self):
        self.b.update_state([], {**ZERO, 'RX': 1, 'RY': -1}, 1)
        self.b.tick(1.016, 0.016)
        moves = [c for c in self.api.calls if c[0] == 'mv']
        self.assertTrue(moves)
        self.assertGreater(moves[-1][1], 0)
        self.assertLess(moves[-1][2], 0)
        self.b.update_state([], ZERO, 1.1)
        before = len(self.api.calls)
        self.b.tick(1.116, 0.016)
        self.assertEqual(len(self.api.calls), before)

    def test_mouse_button(self):
        self.b.update_state(['LB'], ZERO, 1)
        self.b.tick(1.1, 0.015)
        self.assertIn(('md', 'left'), self.api.calls)
        self.assertIn(('mu', 'left'), self.api.calls)

    def test_disconnect_releases_everything(self):
        self.b.update_state(['B', 'X', 'RB'], {**ZERO, 'LY': -0.9, 'RX': 1}, 1)
        self.b.release_all()
        self.assertIn(('ku', 'w'), self.api.calls)
        self.assertIn(('ku', 'shift'), self.api.calls)
        self.assertIn(('mu', 'right'), self.api.calls)
        self.assertEqual(self.b.refs, {})
        self.assertEqual(self.b.axes, ZERO)

    def test_network_hmac_and_tampering(self):
        pkt = sender.encode_packet('some-secret', 'session1', 12, {'buttons':['A'], 'axes':ZERO})
        decoded = receiver.decode_packet(pkt, 'some-secret')
        self.assertEqual(decoded['seq'], 12)
        self.assertEqual(decoded['buttons'], ['A'])
        self.assertIsNone(receiver.decode_packet(pkt, 'bad-secret'))
        self.assertIsNone(receiver.decode_packet(pkt + b'changed', 'some-secret'))

    def test_sender_hat_and_axes(self):
        s = sender.GamepadState.__new__(sender.GamepadState)
        s.info = {code: None for code in (*sender.STICKS, *sender.TRIGGERS, sender.ABS_HAT0X, sender.ABS_HAT0Y)}
        s.digital, s.hat, s.trigger_keys, s.analog_triggers = set(), set(), set(), set()
        s.axes, s.triggers, s.hat_xy = {k:0 for k in sender.AXIS_NAMES}, {'LT':0,'RT':0}, [0,0]
        s.update(sender.EV_ABS, sender.ABS_HAT0X, -1)
        s.update(sender.EV_ABS, sender.ABS_HAT0Y, -1)
        self.assertEqual(s.buttons, {'DPAD_LEFT', 'DPAD_UP'})
        s.update(sender.EV_ABS, sender.ABS_HAT0X, 0)
        self.assertEqual(s.buttons, {'DPAD_UP'})
        s.update(sender.EV_ABS, sender.ABS_RX, 32767)
        self.assertGreater(s.axes['RX'], 0.99)
        s.update(sender.EV_ABS, sender.ABS_Z, 240)
        self.assertIn('LT', s.buttons)
        s.update(sender.EV_ABS, sender.ABS_Z, 0)
        self.assertNotIn('LT', s.buttons)

    def test_sender_gamepad_match(self):
        self.assertTrue(sender.is_gamepad('Microsoft X-Box 360 pad 0'))
        self.assertFalse(sender.is_gamepad('Bluetooth Keyboard'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
