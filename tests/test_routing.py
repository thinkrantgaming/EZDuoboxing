"""Two independent receivers; routing, loss, modifiers and native input integration."""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import deck_sender as sender
import sender_common
import windows_receiver as receiver
from test_bridge import FakeAPI, ZERO
from test_recovery import report

HOSTS = {
    'host1': dict(ip='192.0.2.1', port=50505, button='R5', token='one'),
    'host2': dict(ip='192.0.2.2', port=50505, button='L5', token='two'),
}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.native = sender.GripReader(True, touchpads='pressure',
                                       routes={n: h['button'] for n, h in HOSTS.items()})
        self.native.fds = {10: '/fake'}
        self.state = mock.Mock()
        self.state.snapshot.side_effect = lambda: {'buttons': ['LT', 'A'], 'axes': ZERO.copy()}
        self.apis = {n: FakeAPI() for n in HOSTS}
        self.bridges = {n: receiver.InputBridge(a) for n, a in self.apis.items()}
        self.links = {n: receiver.ReceiverSession(b) for n, b in self.bridges.items()}
        self.seq = 0

    def native_report(self, low=0, high=0, now=1, pad=None):
        data = bytearray(report(low, high))
        if pad:
            struct.pack_into('<I', data, 8, low | (1 << 19))
            struct.pack_into('<hh', data, 16, 0, 25000)
            struct.pack_into('<H', data, 56, 3500)
        with mock.patch.object(sender.os, 'read', side_effect=[bytes(data), BlockingIOError]):
            self.native.poll(now)

    def forward(self, now=1):
        snapshots = sender.routed_snapshots(self.state, self.native, now, HOSTS)
        self.seq += 1
        for name, snapshot in snapshots.items():
            packet = sender.encode_packet(HOSTS[name]['token'], 'test', self.seq, snapshot)
            message = receiver.decode_packet(packet, HOSTS[name]['token'])
            self.assertIsNotNone(message)
            self.links[name].accept(message, now)
        self.assertLessEqual(sum(s['healer_active'] for s in snapshots.values()), 1)
        return snapshots

    def test_no_selector_blocks_all_hosts(self):
        self.native_report()
        result = self.forward()
        self.assertTrue(all(not s['healer_active'] for s in result.values()))
        self.assertTrue(all(not a.calls for a in self.apis.values()))

    def test_both_orders_select_first_and_use_opposite_as_action(self):
        for first, opposite, name in [(0x10000, 'L5', 'host1'), (0x8000, 'R5', 'host2')]:
            with self.subTest(name=name):
                self.native_report(0)
                self.native_report(first)
                result = self.forward()
                self.assertTrue(result[name]['healer_active'])
                self.assertNotIn(HOSTS[name]['button'], result[name]['buttons'])
                self.native_report(0x18000)
                result = self.forward()
                self.assertIn(opposite, result[name]['buttons'])
                self.assertIn(('kd', '7'), self.apis[name].calls)
                other = 'host2' if name == 'host1' else 'host1'
                self.assertFalse(result[other]['healer_active'])
                self.native_report(first)
                self.assertNotIn(opposite, self.forward()[name]['buttons'])
                self.assertEqual(self.native.router.active, name)

    def test_releasing_selector_does_not_switch_to_held_opposite(self):
        self.native_report(0x10000)
        self.forward()
        self.native_report(0x18000)
        self.forward()
        self.native_report(0x8000)
        result = self.forward()
        self.assertTrue(all(not s['healer_active'] for s in result.values()))
        self.assertEqual(self.bridges['host1'].refs, {})
        # Even re-pressing R5 while L5 stays held must not rearm.
        self.native_report(0x18000)
        self.assertIsNone(self.native.router.active)
        self.native_report(0)
        self.native_report(0x8000)
        self.assertTrue(self.forward()['host2']['healer_active'])

    def test_simultaneous_selectors_require_both_released(self):
        for low in (0x18000, 0x10000, 0x18000, 0x8000):
            self.native_report(low)
            self.assertIsNone(self.native.router.active)
        self.native_report(0)
        self.native_report(0x10000)
        self.assertEqual(self.native.router.active, 'host1')

    def test_stale_native_releases_both_and_requires_reselection(self):
        self.native_report(0x8000)
        self.forward()
        self.forward(1.6)
        self.assertTrue(all(not b.refs for b in self.bridges.values()))
        self.native_report(0x8000, now=1.7)
        self.assertIsNone(self.native.router.active)
        self.native_report(0, now=1.8)
        self.native_report(0x8000, now=1.9)
        self.assertTrue(self.forward(1.9)['host2']['healer_active'])

    def test_disconnect_and_reattach_do_not_replay_held_selector(self):
        self.native_report(0x10000)
        self.forward()
        with mock.patch.object(sender.os, 'read', return_value=b''), mock.patch.object(sender.os, 'close'):
            self.native.poll(1.1)
        self.forward(1.1)
        self.native.fds = {10: '/fake'}
        self.native_report(0x10000, now=1.2)
        self.assertIsNone(self.native.router.active)
        self.assertTrue(all(not b.refs for b in self.bridges.values()))

    def test_virtual_device_loss_disables_native_buttons_too(self):
        self.native_report(0x18000)  # Release ambiguous press first.
        self.native_report(0)
        self.native_report(0x10000)
        self.native_report(0x18000)
        self.state = None
        self.assertTrue(all(not s['healer_active'] for s in self.forward().values()))

    def test_pressure_pad_works_with_either_selector_and_clears_on_release(self):
        for low, name in [(0x10000, 'host1'), (0x8000, 'host2')]:
            self.native_report(0)
            for _ in range(3):
                self.native_report(low, pad=True)
            self.assertIn('LPAD_UP', self.forward()[name]['buttons'])
            self.native_report(0, pad=True)
            self.assertEqual(self.native.pad_buttons, set())
            self.assertTrue(all(not s['healer_active'] for s in self.forward().values()))

    def test_shift_then_ability_and_route_release_on_each_host(self):
        with mock.patch.dict(receiver.config.BINDINGS, {
            'LT': {'mode': 'hold', 'keys': ['shift']},
            'A': {'mode': 'tap', 'keys': ['1']},
        }):
            for low, name in [(0x10000, 'host1'), (0x8000, 'host2')]:
                self.state.snapshot.side_effect = lambda: {'buttons': ['LT'], 'axes': ZERO.copy()}
                self.native_report(low)
                self.forward()
                self.state.snapshot.side_effect = lambda: {'buttons': ['LT', 'A'], 'axes': ZERO.copy()}
                self.forward()
                calls = self.apis[name].calls
                self.assertLess(calls.index(('kd', 'shift')), calls.index(('kd', '1')))
                self.native_report(0)
                self.forward()
                self.assertFalse(self.bridges[name].pending_taps)
                self.assertFalse(self.bridges[name].refs)

    def test_edges_within_one_native_read_batch_are_not_lost(self):
        snapshots = []
        with mock.patch.object(sender.os, 'read', side_effect=[
                report(0x8000), report(0x18000), report(0x8000), report(0), BlockingIOError]):
            self.native.poll(1, lambda: snapshots.append(self.forward()))
        self.assertEqual([s['host2']['buttons'].count('R5') for s in snapshots], [0, 1, 0, 0])
        self.assertTrue(all(not s['host1']['healer_active'] for s in snapshots))

    def test_reordered_old_active_packet_cannot_revive_previous_host(self):
        self.native_report(0x10000)
        old = self.forward()['host1']
        self.native_report(0)
        self.forward()
        self.native_report(0x8000)
        self.forward()
        self.assertFalse(self.links['host1'].accept({'session': 'test', 'seq': 1, **old}, 1.1))
        self.assertFalse(self.bridges['host1'].refs)

    def test_configurable_l4_selector_and_r5_ability(self):
        router = sender.RouteSelector({'a': 'L4', 'b': 'R4'})
        self.assertEqual(router.update({'L4'}), 'a')
        self.assertEqual(router.update({'L4', 'R5', 'R4'}), 'a')
        self.assertIsNone(router.update({'R4'}))
        router.update(set())
        self.assertEqual(router.update({'R4'}), 'b')
        self.assertEqual(sender.decode_native_grips(report(0x18000, 0x600)), sender.NATIVE_GRIPS)

    def test_action_grips_can_be_disabled_without_disabling_routes(self):
        self.native_report(0x8000)
        self.native_report(0x18000)
        snaps = sender.routed_snapshots(self.state, self.native, 1, HOSTS, include_grips=False)
        self.assertTrue(snaps['host2']['healer_active'])
        self.assertNotIn('R5', snaps['host2']['buttons'])


class ConfigAndTransportTests(unittest.TestCase):
    def load(self, hosts, probe=False):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'config.py'
            path.write_text('HOSTS = ' + repr(hosts))
            return sender.load_hosts(path, probe=probe)[0]

    def test_distinct_ips_same_port_and_distinct_ports_same_ip(self):
        self.assertEqual(self.load(HOSTS), HOSTS)
        hosts = {n: dict(h) for n, h in HOSTS.items()}
        hosts['host2'].update(ip=hosts['host1']['ip'], port=50506)
        self.assertEqual(self.load(hosts), hosts)

    def test_ambiguous_or_invalid_config_rejected(self):
        for changes in [dict(button='R5'), dict(button='UNKNOWN'), dict(port=0),
                        dict(port=True), dict(ip='BAD'), dict(token=''),
                        dict(ip=HOSTS['host1']['ip']), dict(enabled='False')]:
            with self.subTest(changes=changes):
                hosts = {n: dict(h) for n, h in HOSTS.items()}
                hosts['host2'].update(changes)
                with self.assertRaises(ValueError): self.load(hosts)

    def test_probe_accepts_placeholders_and_disabled_host_is_ignored(self):
        hosts = {n: dict(h) for n, h in HOSTS.items()}
        hosts['host2']['ip'] = 'YOUR_VM_IP'
        self.assertEqual(len(self.load(hosts, probe=True)), 2)
        hosts['host2']['enabled'] = False
        self.assertEqual(set(self.load(hosts)), {'host1'})

    def test_one_failed_network_does_not_block_other_and_neutral_is_sent_first(self):
        bad, good = mock.Mock(), mock.Mock()
        bad.send.return_value = False
        order = []
        bad.send.side_effect = lambda *args: order.append('host1') or False
        good.send.side_effect = lambda *args: order.append('host2') or True
        with mock.patch.object(sender_common, 'RetryingUDP', side_effect=[bad, good]):
            dest = sender.Destinations(HOSTS)
        snaps = {'host1': sender.neutral_snapshot(),
                 'host2': dict(buttons=['R5'], axes=ZERO.copy(), healer_active=True)}
        dest.send(snaps, 's', 1, 1)
        self.assertEqual(order, ['host1', 'host2'])
        self.assertFalse(receiver.decode_packet(bad.send.call_args.args[0], 'one')['healer_active'])
        self.assertEqual(receiver.decode_packet(good.send.call_args.args[0], 'two')['buttons'], ['R5'])
        self.assertIsNone(receiver.decode_packet(good.send.call_args.args[0], 'one'))
        dest.close()
        bad.close.assert_called_once()
        good.close.assert_called_once()


class SenderMainTests(unittest.TestCase):
    def run_main(self, probe=False):
        state = mock.Mock()
        state.snapshot.side_effect = lambda: {'buttons': ['LT'], 'axes': ZERO.copy()}
        selector = mock.Mock()
        selector.select.side_effect = [[], KeyboardInterrupt]
        native = mock.Mock()
        native.poll.return_value = False
        native.active_host.return_value = 'host2'
        native.buttons = {'R5'}
        native.pad_buttons = {'LPAD_UP'}
        network = [mock.Mock(), mock.Mock()]
        with tempfile.TemporaryDirectory() as folder:
            config_path = Path(folder)/'config.py'
            config_path.write_text('HOSTS = ' + repr(HOSTS) + "\nGRIPS = True\nTOUCHPADS = 'pressure'\n")
            argv = ['deck_sender.py', '--config', str(config_path), '--device', '/fake']
            if probe:
                argv.append('--probe')
            with mock.patch('sys.argv', argv), \
                 mock.patch.object(sender, 'GripReader', return_value=native) as reader, \
                 mock.patch.object(sender, 'GamepadState', return_value=state), \
                 mock.patch.object(sender, 'device_name', return_value='test pad'), \
                 mock.patch.object(sender.os, 'open', return_value=10), \
                 mock.patch.object(sender.os, 'close'), \
                 mock.patch.object(sender.selectors, 'DefaultSelector', return_value=selector), \
                 mock.patch.object(sender_common, 'RetryingUDP', side_effect=network) as transport, \
                 mock.patch.object(sender.time, 'monotonic', side_effect=range(10, 100, 2)):
                sender.main()
            self.assertEqual(reader.call_args.kwargs['routes'], {'host1': 'R5', 'host2': 'L5'})
            self.assertEqual(reader.call_args.args[2], 'pressure')
        return transport, network

    def test_config_launch_sends_to_both_and_shutdown_releases_both(self):
        transport, networks = self.run_main()
        self.assertEqual(transport.call_count, 2)
        for name, network in zip(HOSTS, networks):
            packets = [receiver.decode_packet(c.args[0], HOSTS[name]['token'])
                       for c in network.send.call_args_list]
            if name == 'host1':
                self.assertTrue(all(not p['healer_active'] for p in packets))
            else:
                self.assertEqual(packets[0]['buttons'], ['LPAD_UP', 'LT', 'R5'])
            self.assertFalse(packets[-1]['healer_active'])
            self.assertEqual(packets[-1]['buttons'], [])
            network.close.assert_called_once()

    def test_config_probe_creates_no_network_transports(self):
        transport, _ = self.run_main(probe=True)
        transport.assert_not_called()


if __name__ == '__main__':
    unittest.main()
