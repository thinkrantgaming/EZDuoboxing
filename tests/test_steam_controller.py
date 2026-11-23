"""Synthetic fixtures for SDL-documented Triton reports; no real hardware access."""
import struct
import unittest
from unittest import mock

import deck_sender as sender
from test_bridge import ZERO
from test_recovery import report as deck_report
from test_routing import HOSTS


def triton(report_id=0x45, buttons=0, left=(0, 0, 0), right=(0, 0, 0), padded=False):
    data = bytearray(64 if padded else 46)
    data[0:2] = bytes((report_id, 123))
    struct.pack_into('<I', data, 2, buttons)
    if report_id == 0x47:
        struct.pack_into('<H', data, 18, 65535)  # pad timestamp, NOT X position
    struct.pack_into('<hhHhhH', data, 20 if report_id == 0x47 else 18, *left, *right)
    return bytes(data)


class DecodeTests(unittest.TestCase):
    def test_each_grip_is_independent_across_all_state_formats(self):
        for report_id in (0x42, 0x45, 0x47):
            for name, mask in [('R5', 0x100), ('L5', 0x40000), ('R4', 0x80), ('L4', 0x20000)]:
                for padded in (False, True):
                    with self.subTest(report_id=report_id, name=name, padded=padded):
                        normalized = sender.normalize_native_report(triton(report_id, mask, padded=padded), 'steam')
                        self.assertEqual(sender.decode_native_grips(normalized), {name})

    def test_known_bytes_fixture(self):
        # Report 45, sequence 7b, R5+L5+L4+R4. All other controls neutral.
        raw = bytes.fromhex('45 7b 80 01 06 00') + bytes(40)
        self.assertEqual(sender.decode_native_grips(sender.normalize_native_report(raw, 'steam')),
                         {'R5', 'L5', 'R4', 'L4'})

    def test_steam_system_button_and_capacitive_grip_sense_are_not_selectors(self):
        raw = triton(buttons=0x10000 | 0x30000000)
        self.assertEqual(sender.decode_native_grips(sender.normalize_native_report(raw, 'steam')), set())

    def test_signed_xy_pressure_and_touch_click_bits_for_both_pads(self):
        for report_id in (0x42, 0x45, 0x47):
            for prefix, touch, click, left, right, expected in (
                ('LPAD', 25, 26, (-25000, 0, 4000), (0, 0, 0), 'LPAD_LEFT'),
                ('RPAD', 21, 22, (0, 0, 0), (0, -25000, 4000), 'RPAD_DOWN'),
            ):
                for mode in ('pressure', 'touch', 'click'):
                    raw = triton(report_id, (1 << touch) | (1 << click) | 0x100, left, right)
                    normalized = sender.normalize_native_report(raw, 'steam')
                    pad = sender.TouchpadDirections(mode, settle_reports=1)
                    self.assertEqual(pad.update(normalized), {expected})

    def test_pressure_release_and_no_touch_reject_resting_pad(self):
        pad = sender.TouchpadDirections('pressure', settle_reports=1)
        for pressure, touch, expected in [(3500, True, {'LPAD_UP'}), (2000, True, {'LPAD_UP'}),
                                          (1700, True, set()), (3500, False, set())]:
            raw = triton(buttons=0x100 | ((1 << 25) if touch else 0), left=(0, 25000, pressure))
            self.assertEqual(pad.update(sender.normalize_native_report(raw, 'steam')), expected)

    def test_wrong_device_format_unknown_and_truncated_reports_are_rejected(self):
        self.assertIsNone(sender.normalize_native_report(deck_report(0x10000), 'steam'))
        self.assertIsNone(sender.normalize_native_report(triton(), 'deck'))
        for length in range(46):
            self.assertIsNone(sender.normalize_native_report(triton()[:length], 'steam'))
        for raw in (bytes(64), b'\x43'+bytes(63), b'\x79\x02', triton()+bytes(30)):
            self.assertIsNone(sender.normalize_native_report(raw, 'steam'))
        deck = deck_report(0x10000)
        self.assertEqual(sender.normalize_native_report(deck, 'deck'), deck)


class DiscoveryTests(unittest.TestCase):
    def test_usb_ble_and_both_dongle_ids_detected_but_deck_and_legacy_excluded(self):
        products = [0x1302, 0x1303, 0x1304, 0x1305, 0x1205, 0x1102]
        paths = [f'/dev/hidraw{i}' for i in range(len(products))]
        info = {p: (5 if product == 0x1303 else 3, 0x28de, product, 'controller')
                for p, product in zip(paths, products)}
        with mock.patch.object(sender.glob, 'glob', return_value=paths), \
             mock.patch.object(sender, 'hidraw_info', side_effect=info.get):
            self.assertEqual(list(sender.native_hidraw_paths('steam')), paths[:4])
            self.assertEqual(list(sender.deck_hidraw_paths()), [paths[4]])

    def test_sysfs_hid_identity_parsing_and_invalid_identity(self):
        with mock.patch.object(sender.Path, 'read_text', return_value='HID_ID=0005:000028DE:00001303\nHID_NAME=Steam Controller\n'):
            self.assertEqual(sender.hidraw_info('/dev/hidraw4'), (5, 0x28de, 0x1303, 'Steam Controller'))
        for text in ('HID_ID=broken\n', 'HID_NAME=Steam\n'):
            with mock.patch.object(sender.Path, 'read_text', return_value=text):
                self.assertIsNone(sender.hidraw_info('/dev/hidraw4'))

    def test_ambiguous_virtual_gamepads_require_explicit_selection(self):
        with mock.patch.object(sender.glob, 'glob', return_value=['/dev/input/event1', '/dev/input/event2']), \
             mock.patch.object(sender, 'device_name', return_value='Microsoft X-Box 360 pad 0'):
            self.assertEqual(sender.gamepad_choices(strict=True), [])
            self.assertEqual(sender.gamepad_choices('/dev/input/event2', strict=True), ['/dev/input/event2'])
        self.assertTrue(sender.is_gamepad('Steam Virtual Gamepad'))
        self.assertFalse(sender.is_gamepad('Steam Controller'))


class NativeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.native = sender.GripReader(True, touchpads='pressure', controller='steam',
                                       routes={n: h['button'] for n, h in HOSTS.items()})
        self.native.fds = {10: '/fake'}
        self.native.last_report = 1
        self.state = mock.Mock()
        self.state.snapshot.side_effect = lambda: dict(buttons=['A'], axes=ZERO.copy())

    def poll(self, reports, now=1):
        seen = []
        with mock.patch.object(sender.os, 'read', side_effect=[*reports, BlockingIOError]):
            self.native.poll(now, lambda: seen.append(sender.routed_snapshots(self.state, self.native, now, HOSTS)))
        return seen

    def test_both_selectors_opposite_actions_pads_and_release_all_formats(self):
        for rid in (0x42, 0x45, 0x47):
            for grip, host, opposite in [(0x100, 'host1', 'L5'), (0x40000, 'host2', 'R5')]:
                self.poll([triton(rid)])
                self.poll([triton(rid, grip)])
                raw = triton(rid, 0x40100 | (1 << 25), left=(0, 25000, 4000))
                seen = self.poll([raw, raw, raw])
                self.assertIn(opposite, seen[-1][host]['buttons'])
                self.assertIn('LPAD_UP', seen[-1][host]['buttons'])
                self.assertNotIn(HOSTS[host]['button'], seen[-1][host]['buttons'])
                released = self.poll([triton(rid)])[-1]
                self.assertTrue(all(not s['healer_active'] for s in released.values()))

    def test_deck_reports_never_select_remote_when_steam_mode_is_active(self):
        self.assertEqual(self.poll([deck_report(0x10000)]), [])
        self.assertIsNone(self.native.active_host(1))

    def test_wireless_disconnect_immediately_releases_and_requires_neutral(self):
        for status in (0x46, 0x79):
            self.poll([triton(), triton(buttons=0x100)])
            seen = self.poll([bytes((status, 1))])
            self.assertTrue(all(not s['healer_active'] for s in seen[-1].values()))
            self.poll([triton(buttons=0x100)])
            self.assertIsNone(self.native.router.active)
            self.poll([triton(), triton(buttons=0x40000)])
            self.assertEqual(self.native.router.active, 'host2')
            self.poll([triton()])

    def test_native_timeout_releases_and_rescans_for_transport_change(self):
        self.poll([triton(buttons=0x100)])
        with mock.patch.object(sender.os, 'read', side_effect=BlockingIOError), mock.patch.object(sender.os, 'close'):
            self.native.poll(1.6)
        self.assertIsNone(self.native.active_host(1.6))
        self.assertFalse(self.native.fds)
        with mock.patch.object(sender, 'native_hidraw_paths', return_value=['/new']) as paths, \
             mock.patch.object(sender.os, 'open', return_value=12), \
             mock.patch.object(sender.os, 'read', side_effect=[triton(), triton(buttons=0x40000), BlockingIOError]):
            self.native.poll(4)
        paths.assert_called_once_with('steam')
        self.assertEqual(self.native.router.active, 'host2')
        self.assertEqual(self.native.active_fd, 12)

    def test_status_and_malformed_packets_do_not_renew_active_input(self):
        self.poll([triton(buttons=0x100)])
        self.poll([b'\x43'+bytes(63), triton()[:12]], 1.4)
        self.assertEqual(self.native.last_report, 1)
        self.assertIsNone(self.native.active_host(1.6))


if __name__ == '__main__':
    unittest.main()
