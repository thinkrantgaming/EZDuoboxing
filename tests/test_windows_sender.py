"""Windows sender tests with fake HID and input APIs. No hardware or network I/O."""
import argparse
import importlib
import struct
import unittest
from unittest import mock

import windows_sender as sender
import sender_common as common
import windows_receiver as receiver

ZERO = dict.fromkeys(common.AXIS_NAMES, 0.0)
HOSTS = {'host1': dict(button='R5', ip='192.0.2.1', port=50505, token='test'),
         'host2': dict(button='L5', ip='192.0.2.2', port=50505, token='test')}


def report(bits=0, report_id=0x45, triggers=(0, 0), axes=(0, 0, 0, 0), pad=(0, 0, 0)):
    raw = bytearray(46)
    raw[0] = report_id
    struct.pack_into('<Ihhhhhh', raw, 2, bits, *triggers, *axes)
    struct.pack_into('<hhH', raw, 20 if report_id == 0x47 else 18, *pad)
    return bytes(raw)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = sender.ControllerState(HOSTS)
        self.state.update(report(), 1)

    def test_all_face_and_navigation_buttons(self):
        bits = sum(1 << bit for bit in sender.BUTTON_BITS)
        for rid in (0x42, 0x45, 0x47):
            self.state.update(report(bits | 0x100, report_id=rid), 1)
            snap = self.state.snapshots(1)['host1']
            self.assertEqual(set(snap['buttons']), set(sender.BUTTON_BITS.values()))
            self.assertTrue(snap['healer_active'])
            self.assertFalse(self.state.snapshots(1)['host2']['healer_active'])

    def test_local_buttons_never_forward_and_startup_hold_requires_release(self):
        state = sender.ControllerState(HOSTS)
        state.update(report(0x101, triggers=(32767,32767), axes=(32767,32767,32767,32767)), 1)
        self.assertTrue(all(not s['healer_active'] for s in state.snapshots(1).values()))
        state.update(report(), 2)
        state.update(report(0x101), 2)
        self.assertEqual(state.snapshots(2)['host1']['buttons'], ['A'])

    def test_axis_sign_and_limits_and_trigger_hysteresis(self):
        self.state.update(report(0x100, triggers=(32767,0), axes=(-32768,32767,32767,-32768)), 1)
        snap = self.state.snapshots(1)['host1']
        self.assertEqual(snap['axes'], dict(LX=-1, LY=-1, RX=1, RY=1))
        self.assertIn('LT', snap['buttons'])
        self.state.update(report(0x100, triggers=(15000,20000)), 1.1)
        self.assertEqual(self.state.triggers, {'LT','RT'})
        self.state.update(report(0x100, triggers=(10000,10000)), 1.2)
        self.assertEqual(self.state.triggers, set())

    def test_opposite_grip_and_release_lockout(self):
        self.state.update(report(0x100), 1)
        self.state.update(report(0x40100), 1)
        self.assertEqual(self.state.snapshots(1)['host1']['buttons'], ['L5'])
        self.state.update(report(0x40000), 1)
        self.assertTrue(all(not s['healer_active'] for s in self.state.snapshots(1).values()))
        self.state.update(report(), 1)
        self.state.update(report(0x40000), 1)
        self.state.update(report(0x40100), 1)
        self.assertEqual(self.state.snapshots(1)['host2']['buttons'], ['R5'])

    def test_pressure_pad_and_timeout_release(self):
        for _ in range(3): self.state.update(report(0x100 | (1 << 25), pad=(0,25000,4000)), 1)
        self.assertIn('LPAD_UP', self.state.snapshots(1)['host1']['buttons'])
        self.assertTrue(all(not s['healer_active'] for s in self.state.snapshots(1.6).values()))
        self.state.update(report(0x100), 2)
        self.assertFalse(self.state.snapshots(2)['host1']['healer_active'])

    def test_receiver_roundtrip_shift_then_one_and_release(self):
        api = mock.Mock()
        bridge = receiver.InputBridge(api)
        link = receiver.ReceiverSession(bridge)
        def forward(seq):
            packet = common.encode_packet('test', 's', seq, self.state.snapshots(1)['host1'])
            link.accept(receiver.decode_packet(packet, 'test'), 1)
        with mock.patch.dict(receiver.config.BINDINGS, {'RT': dict(mode='hold', keys=['shift']), 'A': dict(mode='tap', keys=['1'])}):
            self.state.update(report(0x100, triggers=(0,32767)), 1)
            forward(1)
            self.state.update(report(0x101, triggers=(0,32767)), 1)
            forward(2)
            self.assertEqual(api.keyDown.call_args_list, [mock.call('shift'), mock.call('1')])
            self.state.update(report(), 1)
            forward(3)
        self.assertFalse(bridge.refs)
        self.assertFalse(bridge.pending_taps)

    def test_malformed_and_status_do_not_renew_state(self):
        self.state.update(report(0x101), 1)
        self.assertFalse(self.state.update(b'\x43'+bytes(63), 1.4))
        self.assertEqual(self.state.last_report, 1)
        self.assertFalse(self.state.snapshots(1.6)['host1']['healer_active'])


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.hid = mock.Mock()
        self.hid.enumerate.return_value = [dict(vendor_id=0x28de,product_id=0x1304,path=b'puck')]
        self.handle = self.hid.device.return_value
        self.state = sender.ControllerState(HOSTS)
        self.reader = sender.HidReader(self.hid, self.state)
        self.seen = []

    def poll(self, now, reports):
        self.handle.read.side_effect = [*reports, []]
        self.reader.poll(now, lambda: self.seen.append(self.state.snapshots(now)))

    def test_open_read_edges_and_wireless_disconnect_without_writes(self):
        self.poll(1, [report(), report(0x101), report(0x40101), b'\x79\x01'])
        self.handle.open_path.assert_called_once_with(b'puck')
        self.handle.set_nonblocking.assert_called_once_with(1)
        self.assertTrue(any(s['host1']['healer_active'] for s in self.seen))
        self.assertTrue(all(not s['healer_active'] for s in self.seen[-1].values()))
        self.handle.write.assert_not_called()
        self.handle.send_feature_report.assert_not_called()

    def test_io_error_releases_and_reopens(self):
        self.poll(1, [report(), report(0x101)])
        self.handle.read.side_effect = OSError('removed')
        self.reader.poll(1.1, lambda: self.seen.append(self.state.snapshots(1.1)))
        self.assertFalse(self.seen[-1]['host1']['healer_active'])
        self.poll(4, [report(0x101)])
        self.assertEqual(self.handle.open_path.call_count, 2)
        self.assertFalse(self.state.snapshots(4)['host1']['healer_active'])
        self.poll(4.1, [report(), report(0x101)])
        self.assertTrue(self.state.snapshots(4.1)['host1']['healer_active'])

    def test_silent_timeout_and_unknown_reports_release(self):
        self.poll(1, [report(),report(0x101)])
        self.poll(1.6, [b'\x43'+bytes(63)])
        self.assertFalse(self.state.valid)
        self.assertFalse(self.reader.handles)
        self.assertFalse(self.seen[-1]['host1']['healer_active'])

    def test_open_failure_keeps_retrying(self):
        self.handle.open_path.side_effect = OSError('access denied')
        self.reader.poll(1, lambda: None)
        self.reader.poll(4, lambda: None)
        self.assertEqual(self.handle.open_path.call_count, 2)
        self.assertFalse(self.state.valid)

    def test_other_interfaces_cannot_overwrite_active_input(self):
        self.poll(1, [report(),report(0x101)])
        other = mock.Mock()
        other.read.side_effect = [report(), []]
        self.reader.handles[b'other'] = other
        self.poll(1.1, [])
        self.assertTrue(self.state.snapshots(1.1)['host1']['healer_active'])


class LaunchTests(unittest.TestCase):
    def test_probe_has_no_network_transport(self):
        with mock.patch.object(common, 'RetryingUDP') as udp:
            output = sender.Output(HOSTS, probe=True)
            output.send({n: common.neutral_snapshot() for n in HOSTS}, 1)
            output.close()
        udp.assert_not_called()

    def test_loop_shutdown_sends_neutral_and_closes(self):
        args = argparse.Namespace(touchpads=None,pad_press_pressure=2500,pad_release_pressure=1800,
                                  hid_path=None,debug_native=False,debug_touchpads=False,probe=False)
        with mock.patch.object(sender, 'HidReader') as reader, mock.patch.object(sender, 'Output') as output:
            reader.return_value.poll.side_effect = KeyboardInterrupt
            sender.run(mock.Mock(), HOSTS, args, {})
        reader.return_value.close.assert_called_once()
        snapshots = output.return_value.send.call_args.args[0]
        self.assertTrue(all(not s['healer_active'] for s in snapshots.values()))
        output.return_value.close.assert_called_once()

    def test_single_receiver_cli_with_existing_config_untouched(self):
        with mock.patch.object(sender.sys, 'platform', 'win32'), \
             mock.patch('sys.argv', ['windows_sender.py','192.0.2.10','--probe']), \
             mock.patch.dict('sys.modules', {'hid': mock.Mock()}), \
             mock.patch.object(sender, 'run') as run:
            sender.main()
        hosts = run.call_args.args[1]
        self.assertEqual(set(hosts), {'host1'})
        self.assertEqual(hosts['host1']['button'], 'R5')
        self.assertEqual(hosts['host1']['ip'], '192.0.2.10')

    def test_portable_import_does_not_require_linux_fcntl(self):
        with mock.patch.dict('sys.modules', {'fcntl': None}):
            importlib.reload(sender)


if __name__ == '__main__':
    unittest.main()
