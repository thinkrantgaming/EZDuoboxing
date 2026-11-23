import struct
import unittest
from unittest import mock
import deck_sender as sender
import windows_receiver as receiver
from test_touchpads import pad_report
from test_bridge import FakeAPI, ZERO


class PadStabilityTests(unittest.TestCase):
    def setUp(self):
        self.pad = sender.TouchpadDirections('click')
        self.down = pad_report(right=(0, -24000))
        self.up = pad_report(right=(0, 24000))
        self.release = pad_report(click=False)

    def feed(self, report, count=3):
        outputs = []
        for _ in range(count):
            outputs.append(self.pad.update(report))
        return outputs

    def test_initial_wrong_or_center_report_does_not_latch(self):
        self.assertEqual(self.pad.update(self.up), set())
        self.assertEqual(self.pad.update(pad_report()), set())
        self.assertEqual(self.feed(self.down), [set(), set(), {'RPAD_DOWN'}])

    def test_no_touch_initial_click_does_not_swallow_press(self):
        self.pad.update(pad_report(right=(0, -24000), touch=False))
        self.assertEqual(self.feed(self.down)[-1], {'RPAD_DOWN'})

    def test_flickering_click_and_opposite_coordinate_do_not_retrigger(self):
        self.feed(self.down)
        self.assertEqual(self.pad.update(self.release), {'RPAD_DOWN'})
        self.assertEqual(self.pad.update(self.up), {'RPAD_DOWN'})
        self.assertEqual(self.feed(self.down)[-1], {'RPAD_DOWN'})
        self.assertEqual(self.feed(self.release)[-1], set())

    def test_ten_repeated_presses_reach_receiver_as_ten_actions(self):
        api = FakeAPI()
        bridge = receiver.InputBridge(api)
        now = 1.0
        for _ in range(10):
            for report in [self.down] * 12 + [self.release] * 12:
                buttons = self.pad.update(report)
                bridge.update_state(buttons, ZERO, now)
                bridge.tick(now, 0.01)
                now += 0.01
        self.assertEqual(api.calls.count(('kd', 'f10')), 10)
        self.assertEqual(api.calls.count(('ku', 'f10')), 10)
        self.assertNotIn(('kd', 'f9'), api.calls)

    def test_r5_release_bypasses_debounce(self):
        self.feed(self.down)
        self.assertEqual(self.pad.update(pad_report(r5=False)), set())
        self.assertEqual(self.pad.latched, {})

    def test_touch_mode_requires_stable_sector_changes(self):
        self.pad = sender.TouchpadDirections('touch')
        down = pad_report(right=(0, -24000), click=False)
        up = pad_report(right=(0, 24000), click=False)
        self.feed(down)
        self.assertEqual(self.pad.update(up), {'RPAD_DOWN'})
        self.assertEqual(self.pad.update(down), {'RPAD_DOWN'})
        self.assertEqual(self.feed(up)[-1], {'RPAD_UP'})

    def test_raw_diagnostics_decode_pressure_at_documented_offsets(self):
        raw = bytearray(self.down)
        struct.pack_into('<HH', raw, 56, 1234, 5678)
        line = sender.touchpad_debug_line(raw, {'RPAD_DOWN'})
        self.assertIn('R:touch=1 click=1 x=0 y=-24000 pressure=5678', line)
        self.assertIn('pressure=1234', line)
        self.assertIn('output=RPAD_DOWN', line)

    def test_native_reader_emits_only_settled_edges(self):
        native = sender.GripReader(True, touchpads='click')
        native.fds = {10: '/fake'}
        seen = []
        reports = [self.up, self.down, self.down, self.down, self.release, self.up,
                   self.down, self.release, self.release, self.release]
        with mock.patch.object(sender.os, 'read', side_effect=reports + [BlockingIOError]):
            native.poll(1, lambda: seen.append(native.pad_buttons.copy()))
        # First callback is R5 rising; neither pad direction has settled yet.
        self.assertEqual(seen, [set(), {'RPAD_DOWN'}, set()])


if __name__ == '__main__':
    unittest.main(verbosity=2)
