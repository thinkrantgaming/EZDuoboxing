import struct
import unittest
from unittest import mock
import deck_sender as sender
import windows_receiver as receiver
from test_bridge import FakeAPI, ZERO
from test_recovery import report


def pad_report(left=(0, 0), right=(0, 0), r5=True, touch=True, click=True):
    low = 0x10000 if r5 else 0
    if touch:
        low |= (1 << 19) | (1 << 20)
    if click:
        low |= (1 << 17) | (1 << 18)
    data = bytearray(report(low))
    struct.pack_into('<hhhh', data, 16, *left, *right)
    return bytes(data)


class TouchpadTests(unittest.TestCase):
    def test_all_eight_sectors(self):
        for pad in ('LPAD', 'RPAD'):
            for direction, xy in [('UP', (0, 20000)), ('DOWN', (0, -20000)),
                                  ('LEFT', (-20000, 0)), ('RIGHT', (20000, 0))]:
                with self.subTest(pad=pad, direction=direction):
                    decoder = sender.TouchpadDirections('click', settle_reports=1)
                    data = pad_report(left=xy) if pad == 'LPAD' else pad_report(right=xy)
                    self.assertEqual(decoder.update(data), {pad + '_' + direction})

    def test_r5_required_and_releasing_r5_clears_latch(self):
        decoder = sender.TouchpadDirections('click', settle_reports=1)
        self.assertEqual(decoder.update(pad_report(left=(0, 20000), r5=False)), set())
        self.assertEqual(decoder.update(pad_report(left=(0, 20000))), {'LPAD_UP'})
        self.assertEqual(decoder.update(pad_report(left=(0, 20000), r5=False)), set())
        self.assertEqual(decoder.latched, {})

    def test_center_and_resting_touch_do_not_click(self):
        decoder = sender.TouchpadDirections('click', settle_reports=1)
        self.assertEqual(decoder.update(pad_report(left=(1000, 1000))), set())
        # A center first report must not swallow a later valid direction.
        self.assertEqual(decoder.update(pad_report(left=(20000, 0))), {'LPAD_RIGHT'})
        self.assertEqual(decoder.update(pad_report(left=(20000, 0), click=False)), set())
        self.assertEqual(decoder.update(pad_report(left=(20000, 0))), {'LPAD_RIGHT'})

    def test_click_direction_latches_until_release(self):
        decoder = sender.TouchpadDirections('click', settle_reports=1)
        self.assertEqual(decoder.update(pad_report(left=(0, 20000))), {'LPAD_UP'})
        self.assertEqual(decoder.update(pad_report(left=(20000, 0))), {'LPAD_UP'})
        self.assertEqual(decoder.update(pad_report(click=False)), set())
        self.assertEqual(decoder.update(pad_report(left=(20000, 0))), {'LPAD_RIGHT'})

    def test_touch_mode_and_disabled_mode(self):
        data = pad_report(left=(-20000, 0), click=False)
        self.assertEqual(sender.TouchpadDirections('touch', settle_reports=1).update(data), {'LPAD_LEFT'})
        self.assertEqual(sender.TouchpadDirections('off').update(data), set())
        self.assertEqual(sender.TouchpadDirections('touch', settle_reports=1).update(pad_report(left=(-20000, 0), touch=False)), set())

    def test_both_pads_dpad_and_shift_are_independent(self):
        native = sender.GripReader(True, touchpads='click')
        native.fds = {10: '/fake'}
        native.touchpads.settle_reports = 1
        with mock.patch.object(sender.os, 'read', side_effect=[
                pad_report(left=(0, 20000), right=(20000, 0)), BlockingIOError]):
            native.poll(1)
        state = mock.Mock()
        state.snapshot.return_value = {'buttons': ['B', 'DPAD_UP'], 'axes': ZERO.copy()}
        snapshot = sender.gated_snapshot(state, native, 1, include_pads=True)
        packet = sender.encode_packet('test', 's', 1, snapshot)
        msg = receiver.decode_packet(packet, 'test')
        api = FakeAPI()
        bridge = receiver.InputBridge(api)
        bridge.update_state(msg['buttons'], msg['axes'], 1)
        for key in ('shift', 'f1', 'f5', 'f12'):
            self.assertIn(('kd', key), api.calls)
        self.assertEqual(set(msg['buttons']), {'B', 'DPAD_UP', 'LPAD_UP', 'RPAD_RIGHT'})
        # Same state is not a repeating macro.
        bridge.update_state(msg['buttons'], msg['axes'], 1.01)
        self.assertEqual(api.calls.count(('kd', 'f5')), 1)
        native.close = mock.Mock()  # Fake descriptor: clear state without OS close.
        native.r5 = False
        neutral = sender.gated_snapshot(state, native, 1.02, include_pads=True)
        receiver.ReceiverSession(bridge).accept({'session':'s', 'seq':2, **neutral}, 1.02)
        self.assertEqual(bridge.refs, {})

    def test_native_pad_edges_and_loss(self):
        native = sender.GripReader(True, touchpads='click')
        native.fds = {10: '/fake'}
        native.touchpads.settle_reports = 1
        seen = []
        with mock.patch.object(sender.os, 'read', side_effect=[
                pad_report(left=(0, 20000)), pad_report(click=False), BlockingIOError]):
            native.poll(1, lambda: seen.append(native.pad_buttons.copy()))
        self.assertEqual(seen, [{'LPAD_UP'}, set()])
        with mock.patch.object(sender.os, 'read', side_effect=[
                pad_report(left=(0, 20000)), BlockingIOError]):
            native.poll(1.1)
        with mock.patch.object(sender.os, 'read', side_effect=BlockingIOError), mock.patch.object(sender.os, 'close'):
            native.poll(1.7)
        self.assertEqual(native.pad_buttons, set())
        self.assertEqual(native.touchpads.latched, {})
        self.assertFalse(native.held_r5(1.7))


if __name__ == '__main__':
    unittest.main(verbosity=2)
