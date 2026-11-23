"""Regression tests for local input leaking into remote controls."""
import unittest
from unittest import mock
import deck_sender as sender
import windows_receiver as receiver
from test_bridge import FakeAPI, ZERO
from test_recovery import report


class R5GateTests(unittest.TestCase):
    def setUp(self):
        self.native = sender.GripReader(True)
        self.state = mock.Mock()
        self.state.snapshot.side_effect = lambda: {'buttons': ['LT', 'RT'], 'axes': {**ZERO, 'LX': 1, 'RX': 1}}
        self.api = FakeAPI()
        self.bridge = receiver.InputBridge(self.api)
        self.link = receiver.ReceiverSession(self.bridge)
        self.seq = 0

    def native_report(self, low, now):
        self.native.fds = {10: '/fake'}
        with mock.patch.object(sender.os, 'read', side_effect=[report(low), BlockingIOError]):
            self.native.poll(now)

    def forward(self, now):
        self.seq += 1
        snapshot = sender.gated_snapshot(self.state, self.native, now)
        packet = sender.encode_packet('test', 'session', self.seq, snapshot)
        self.link.accept(receiver.decode_packet(packet, 'test'), now)
        return snapshot

    def test_no_native_r5_confirmation_blocks_everything(self):
        snapshot = self.forward(1)
        self.assertFalse(snapshot['healer_active'])
        self.assertEqual(snapshot['buttons'], [])
        self.assertEqual(snapshot['axes'], ZERO)
        self.assertEqual(self.api.calls, [])

    def test_triggers_cannot_press_shift_without_r5(self):
        with mock.patch.dict(receiver.config.BINDINGS, {
                'LT': {'mode': 'hold', 'keys': ['shift']},
                'RT': {'mode': 'hold', 'keys': ['shift']}}):
            self.native_report(0, 1)
            self.forward(1)
            self.assertEqual(self.api.calls, [])
            self.native_report(0x10000, 1.1)
            self.forward(1.1)
            self.assertEqual(self.api.calls.count(('kd', 'shift')), 1)
            # Virtual triggers still report held, but releasing physical R5 wins.
            self.native_report(0, 1.2)
            self.forward(1.2)
            self.assertEqual(self.api.calls.count(('ku', 'shift')), 1)
            self.assertEqual(self.bridge.refs, {})
            self.assertEqual(self.bridge.axes, ZERO)
            self.forward(1.3)
            self.assertEqual(self.api.calls.count(('kd', 'shift')), 1)

    def test_any_configured_shift_button_requires_r5(self):
        self.state.snapshot.side_effect = lambda: {'buttons': ['Y'], 'axes': ZERO.copy()}
        with mock.patch.dict(receiver.config.BINDINGS, {'Y': {'mode': 'hold', 'keys': ['shift']}}):
            self.forward(1)
            self.assertEqual(self.api.calls, [])
            self.native_report(0x10000, 1.1)
            self.forward(1.1)
            self.assertIn(('kd', 'shift'), self.api.calls)

    def test_stale_native_r5_stops_forwarding_and_releases(self):
        self.native_report(0x10000, 1)
        self.forward(1)
        self.assertTrue(self.bridge.refs)
        self.forward(1.51)
        self.assertEqual(self.bridge.refs, {})
        self.assertEqual(self.bridge.axes, ZERO)

    def test_release_cancels_in_progress_tap_immediately(self):
        self.state.snapshot.side_effect = lambda: {'buttons': ['X'], 'axes': ZERO.copy()}
        self.native_report(0x10000, 1)
        self.forward(1)
        self.assertIn(('kd', 'shift'), self.api.calls)
        self.native_report(0, 1.01)
        self.forward(1.01)
        self.assertIn(('ku', 'shift'), self.api.calls)
        self.assertEqual(self.bridge.pending_taps, [])

    def test_r5_only_edges_trigger_immediate_callback(self):
        self.native.fds = {10: '/fake'}
        seen = []
        with mock.patch.object(sender.os, 'read', side_effect=[
                report(0x10000), report(0), BlockingIOError]):
            self.native.poll(1, lambda: seen.append(self.native.held_r5(1)))
        self.assertEqual(seen, [True, False])

    def test_r5_disconnect_blocks_input(self):
        self.native_report(0x10000, 1)
        self.forward(1)
        with mock.patch.object(sender.os, 'read', return_value=b''), mock.patch.object(sender.os, 'close'):
            self.native.poll(1.1)
        self.forward(1.1)
        self.assertEqual(self.bridge.refs, {})

    def test_receiver_false_gate_overrides_even_non_neutral_payload(self):
        packet = sender.encode_packet('test', 'session', 1, {
            'buttons': ['B'], 'axes': {**ZERO, 'LX': 1}, 'healer_active': False})
        self.link.accept(receiver.decode_packet(packet, 'test'), 1)
        self.assertEqual(self.api.calls, [])

    def test_invalid_gate_type_is_rejected(self):
        packet = sender.encode_packet('test', 'session', 1, {
            'buttons': ['B'], 'axes': ZERO, 'healer_active': 'false'})
        self.assertIsNone(receiver.decode_packet(packet, 'test'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
