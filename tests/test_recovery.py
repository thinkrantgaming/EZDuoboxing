"""Recovery and native-grip tests; no hardware or input injection required."""
import socket
import struct
import unittest
from unittest import mock

import deck_sender as sender
import sender_common
import windows_receiver as receiver
from test_bridge import FakeAPI, ZERO


def message(session='first', seq=1, buttons=(), axes=None):
    packet = sender.encode_packet('test', session, seq,
                                  {'buttons': list(buttons), 'axes': axes or ZERO})
    return receiver.decode_packet(packet, 'test')


def report(low=0, high=0):
    data = bytearray(64)
    data[:4] = b'\x01\x00\x09\x40'
    struct.pack_into('<II', data, 8, low, high)
    return bytes(data)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.bridge = receiver.InputBridge(self.api)
        self.link = receiver.ReceiverSession(self.bridge)

    def test_outage_releases_and_same_sender_recovers(self):
        self.link.accept(message(buttons=['B'], axes={**ZERO, 'LY': -1}), 1)
        self.link.tick(2.1)
        self.assertEqual(self.bridge.refs, {})
        self.assertFalse(self.link.connected)
        self.assertFalse(self.link.accept(message(), 2.2))
        self.assertTrue(self.link.accept(message(seq=2, buttons=['B']), 2.3))
        self.assertEqual(self.api.calls.count(('kd', 'shift')), 2)
        self.link.accept(message(seq=3), 2.4)
        self.assertEqual(self.bridge.refs, {})

    def test_restart_releases_old_holds_and_rejects_retired_sender(self):
        self.link.accept(message(seq=99, buttons=['B']), 1)
        self.link.accept(message(session='new', buttons=['A']), 1.1)
        self.assertIn(('ku', 'shift'), self.api.calls)
        self.assertIn(('kd', '1'), self.api.calls)
        self.assertFalse(self.link.accept(message(seq=100, buttons=['B']), 1.2))
        self.assertEqual(self.link.session, 'new')

    def test_duplicate_and_out_of_order_packets_do_not_repeat_taps(self):
        self.link.accept(message(seq=5, buttons=['A']), 1)
        self.assertFalse(self.link.accept(message(seq=5), 1.1))
        self.assertFalse(self.link.accept(message(seq=4), 1.2))
        self.link.accept(message(seq=6, buttons=['A']), 1.3)
        self.assertEqual(self.api.calls.count(('kd', '1')), 1)
        self.assertEqual(self.link.last_valid, 1.3)

    def test_duplicate_does_not_keep_watchdog_alive(self):
        self.link.accept(message(buttons=['B']), 1)
        self.link.accept(message(buttons=['B']), 1.9)
        self.link.tick(2.1)
        self.assertFalse(self.link.connected)
        self.assertEqual(self.bridge.refs, {})

    def test_socket_reset_preserves_order_and_accepts_new_state(self):
        self.link.accept(message(seq=10, buttons=['B']), 1)
        self.link.disconnect()
        self.assertFalse(self.link.accept(message(seq=9, buttons=['B']), 2))
        self.assertTrue(self.link.accept(message(seq=11, buttons=['Y']), 2.1))
        self.assertIn(('kd', 'tab'), self.api.calls)

    def test_udp_retry_reopens_socket_and_does_not_buffer_inputs(self):
        bad, good = mock.Mock(), mock.Mock()
        bad.sendto.side_effect = OSError('network unreachable')
        factory = mock.Mock(side_effect=[bad, good])
        transport = sender.RetryingUDP(('127.0.0.1', 50505), factory)
        self.assertFalse(transport.send(b'old held input', 1))
        self.assertFalse(transport.send(b'still disconnected', 1.5))
        self.assertTrue(transport.send(b'current neutral state', 2))
        bad.close.assert_called_once()
        good.sendto.assert_called_once_with(b'current neutral state', ('127.0.0.1', 50505))
        transport.close()

    def test_udp_socket_creation_failure_recovers(self):
        good = mock.Mock()
        factory = mock.Mock(side_effect=[OSError('temporarily unavailable'), good])
        transport = sender.RetryingUDP(('127.0.0.1', 50505), factory)
        self.assertFalse(transport.send(b'old', 1))
        self.assertTrue(transport.send(b'new', 2))
        transport.close()

    def test_receiver_main_reopens_socket_after_error(self):
        first, second = mock.MagicMock(), mock.MagicMock()
        for sock in (first, second):
            sock.__enter__.return_value = sock
        first.recvfrom.side_effect = OSError('network reset')
        packet = sender.encode_packet('CHANGE_THIS_PRIVATE_TOKEN', 'new', 1,
                                      {'buttons': ['B'], 'axes': ZERO})
        second.recvfrom.side_effect = [(packet, ('127.0.0.1', 1000)), KeyboardInterrupt]
        with mock.patch.dict('sys.modules', {'pydirectinput': self.api}), \
             mock.patch('sys.argv', ['windows_receiver.py', '--deck-ip', '127.0.0.1']), \
             mock.patch.object(receiver.socket, 'socket', side_effect=[first, second]), \
             mock.patch.object(receiver.time, 'sleep'):
            with self.assertRaises(KeyboardInterrupt):
                receiver.main()
        self.assertIn(('kd', 'shift'), self.api.calls)
        self.assertIn(('ku', 'shift'), self.api.calls)
        second.bind.assert_called_once_with(('0.0.0.0', 50505))

    def test_attach_reconstructs_held_buttons_hat_and_trigger(self):
        def abs_info(_fd, code):
            if code == sender.ABS_HAT0X:
                return (-1, -1, 1, 0, 0, 0)
            if code == sender.ABS_Z:
                return (255, 0, 255, 0, 0, 0)
            return None
        keys = bytearray(96)
        keys[304 // 8] |= 1 << (304 % 8)
        with mock.patch.object(sender, 'abs_info', side_effect=abs_info), \
             mock.patch.object(sender.fcntl, 'ioctl', return_value=bytes(keys)):
            state = sender.GamepadState(10)
        self.assertEqual(state.buttons, {'A', 'LT', 'DPAD_LEFT'})

    def test_sender_main_reattaches_and_sends_neutral_after_device_loss(self):
        state = mock.Mock()
        state.snapshot.return_value = {'buttons': ['B'], 'axes': ZERO.copy()}
        selector = mock.Mock()
        selector.select.side_effect = [[(None, None)], [], KeyboardInterrupt]
        network = mock.Mock()
        with mock.patch('sys.argv', ['deck_sender.py', '127.0.0.1', '--device', '/fake']), \
             mock.patch.object(sender, 'GamepadState', return_value=state), \
             mock.patch.object(sender, 'GripReader') as native, \
             mock.patch.object(sender, 'device_name', return_value='test pad'), \
             mock.patch.object(sender.os, 'open', side_effect=[10, 11]) as opening, \
             mock.patch.object(sender.os, 'close'), \
             mock.patch.object(sender.os, 'read', return_value=b''), \
             mock.patch.object(sender.selectors, 'DefaultSelector', return_value=selector), \
             mock.patch.object(sender_common, 'RetryingUDP', return_value=network), \
             mock.patch.object(sender.time, 'monotonic', side_effect=range(10, 100, 2)):
            native.return_value.poll.return_value = False
            native.return_value.active_host.return_value = 'host1'
            sender.main()
        self.assertEqual(opening.call_count, 2)
        snapshots = [receiver.decode_packet(c.args[0], 'CHANGE_THIS_PRIVATE_TOKEN')
                     for c in network.send.call_args_list]
        self.assertEqual(snapshots[0]['buttons'], ['B'])
        self.assertEqual(snapshots[1]['buttons'], [])
        self.assertEqual(snapshots[-1]['buttons'], [])

    def test_input_queue_overflow_releases_and_resynchronizes(self):
        first, recovered = mock.Mock(), mock.Mock()
        first.snapshot.return_value = {'buttons': ['B'], 'axes': ZERO.copy()}
        recovered.snapshot.return_value = {'buttons': [], 'axes': ZERO.copy()}
        events = b''.join(sender.INPUT_EVENT.pack(0, 0, typ, code, value) for typ, code, value in [
            (sender.EV_SYN, sender.SYN_DROPPED, 0),
            (sender.EV_KEY, 304, 1),  # Must be ignored until synchronization.
            (sender.EV_SYN, sender.SYN_REPORT, 0)])
        selector, network = mock.Mock(), mock.Mock()
        selector.select.side_effect = [[(None, None)], KeyboardInterrupt]
        with mock.patch('sys.argv', ['deck_sender.py', '127.0.0.1', '--device', '/fake']), \
             mock.patch.object(sender, 'GamepadState', side_effect=[first, recovered]) as states, \
             mock.patch.object(sender, 'GripReader') as native, \
             mock.patch.object(sender, 'device_name', return_value='test pad'), \
             mock.patch.object(sender.os, 'open', return_value=10), \
             mock.patch.object(sender.os, 'close'), \
             mock.patch.object(sender.os, 'read', return_value=events), \
             mock.patch.object(sender.selectors, 'DefaultSelector', return_value=selector), \
             mock.patch.object(sender_common, 'RetryingUDP', return_value=network), \
             mock.patch.object(sender.time, 'monotonic', side_effect=range(10, 100, 2)):
            native.return_value.poll.return_value = False
            native.return_value.active_host.return_value = 'host1'
            sender.main()
        self.assertEqual(states.call_count, 2)
        first.update.assert_not_called()
        recovered.update.assert_not_called()
        packets = [receiver.decode_packet(c.args[0], 'CHANGE_THIS_PRIVATE_TOKEN')
                   for c in network.send.call_args_list]
        self.assertEqual(packets[0]['buttons'], ['B'])
        self.assertTrue(all(p['buttons'] == [] for p in packets[1:]))


class GripTests(unittest.TestCase):
    def test_grips_require_r5_and_decode_independently(self):
        self.assertEqual(sender.decode_grips(report(0x8000, 0x600)), set())
        for name, low, high in [('L4', 0, 0x200), ('L5', 0x8000, 0), ('R4', 0, 0x400)]:
            self.assertEqual(sender.decode_grips(report(0x10000 | low, high)), {name})
        self.assertEqual(sender.decode_grips(report(0x18000, 0x600)), {'L4', 'L5', 'R4'})

    def test_wrong_and_short_reports_ignored(self):
        self.assertIsNone(sender.decode_grips(b'bad'))
        self.assertIsNone(sender.decode_grips(bytes(64)))

    def test_grip_bindings_round_trip(self):
        api = FakeAPI()
        bridge = receiver.InputBridge(api)
        msg = message(buttons=['L4', 'L5', 'R4'])
        bridge.update_state(msg['buttons'], msg['axes'], 1)
        bridge.tick(1.1, 0)
        for key in ('6', '7', '8'):
            self.assertIn(('kd', key), api.calls)
            self.assertIn(('ku', key), api.calls)
        self.assertEqual(bridge.refs, {})

    def test_grip_timeout_releases_and_rescans(self):
        reader = sender.GripReader(True)
        reader.fds = {10: '/dev/hidraw0'}
        reader.active_fd, reader.last_report = 10, 1
        reader.buttons = {'L4'}
        with mock.patch.object(sender.os, 'read', side_effect=BlockingIOError), \
             mock.patch.object(sender.os, 'close') as close:
            self.assertTrue(reader.poll(1.6))
            close.assert_called_once_with(10)
        self.assertEqual(reader.buttons, set())
        self.assertFalse(reader.fds)

    def test_grip_r5_release_and_short_tap_not_lost_in_batch(self):
        reader = sender.GripReader(True)
        reader.fds = {10: '/dev/hidraw0'}
        seen = []
        with mock.patch.object(sender.os, 'read', side_effect=[
                report(0x10000, 0x200), report(0, 0x200), BlockingIOError]):
            reader.poll(1, lambda: seen.append(reader.buttons.copy()))
        self.assertEqual(seen, [{'L4'}, set()])

    def test_grip_device_disconnect_releases(self):
        reader = sender.GripReader(True)
        reader.fds = {10: '/dev/hidraw0'}
        reader.active_fd = 10
        reader.buttons = {'L5'}
        with mock.patch.object(sender.os, 'read', return_value=b''), \
             mock.patch.object(sender.os, 'close'):
            self.assertTrue(reader.poll(1))
        self.assertEqual(reader.buttons, set())


if __name__ == '__main__':
    unittest.main(verbosity=2)
