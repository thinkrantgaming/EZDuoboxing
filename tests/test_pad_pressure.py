import struct
import unittest
import deck_sender as sender
from test_touchpads import pad_report


def pressure_report(left=0, right=0, r5=True, touch=True):
    data = bytearray(pad_report(left=(1000, -30000), right=(2000, -30500),
                                click=False, touch=touch, r5=r5))
    struct.pack_into('<HH', data, 56, left, right)
    return bytes(data)


class PressureTests(unittest.TestCase):
    def setUp(self):
        self.pad = sender.TouchpadDirections('pressure')

    def settle(self, **kwargs):
        for _ in range(3):
            result = self.pad.update(pressure_report(**kwargs))
        return result

    def test_press_works_with_click_bit_always_zero(self):
        self.assertEqual(self.settle(right=295), set())
        self.assertEqual(self.settle(right=4015), {'RPAD_DOWN'})
        self.assertEqual(self.settle(right=0), set())
        self.assertEqual(self.settle(left=4410), {'LPAD_DOWN'})

    def test_hysteresis_and_repeated_presses_without_lifting_thumb(self):
        for _ in range(10):
            self.assertEqual(self.settle(right=4000), {'RPAD_DOWN'})
            self.assertEqual(self.settle(right=2000), {'RPAD_DOWN'})
            self.assertEqual(self.settle(right=1307), set())
            # Between thresholds does not start a new press after release.
            self.assertEqual(self.settle(right=2000), set())

    def test_both_pads_independent(self):
        self.assertEqual(self.settle(left=4000, right=4000), {'LPAD_DOWN', 'RPAD_DOWN'})
        self.assertEqual(self.settle(left=1300, right=4000), {'RPAD_DOWN'})

    def test_touch_loss_and_r5_release(self):
        self.settle(right=4000)
        self.assertEqual(self.pad.update(pressure_report(right=4000, r5=False)), set())
        self.assertFalse(self.pad.pressure_held)
        self.settle(right=4000)
        self.assertEqual(self.settle(right=4000, touch=False), set())

    def test_brief_pressure_dropout_does_not_duplicate_action(self):
        self.settle(right=4000)
        self.assertEqual(self.pad.update(pressure_report(right=0)), {'RPAD_DOWN'})
        self.assertEqual(self.pad.update(pressure_report(right=4000)), {'RPAD_DOWN'})

    def test_threshold_validation_and_customization(self):
        with self.assertRaises(ValueError):
            sender.TouchpadDirections('pressure', press_pressure=1000, release_pressure=1000)
        self.pad = sender.TouchpadDirections('pressure', press_pressure=1500, release_pressure=500)
        self.assertEqual(self.settle(right=1600), {'RPAD_DOWN'})
        self.assertEqual(self.settle(right=700), {'RPAD_DOWN'})
        self.assertEqual(self.settle(right=400), set())

    def test_sampled_log_values_classify_down_only(self):
        # Values from the user's sampled log. Hold each for three synthetic
        # reports to test classification, not reconstruction of missing timing.
        for side, samples in [('right', [284, 295, 4015, 2813, 0, 3899, 1936, 64,
                                        2086, 3899, 0, 1185, 4800, 526, 1416, 4465, 1601]),
                              ('left', [1, 284, 1078, 4410, 2475, 1307, 1544, 3361,
                                        1170, 896, 2795, 2402, 1188, 1443, 4054, 1900,
                                        1380, 1307, 4940, 2493])]:
            self.pad.clear()
            expected = 'RPAD_DOWN' if side == 'right' else 'LPAD_DOWN'
            outputs = [self.settle(**{side: value}) for value in samples]
            self.assertIn({expected}, outputs)
            self.assertIn(set(), outputs)
            self.assertTrue(all(output <= {expected} for output in outputs))


if __name__ == '__main__':
    unittest.main(verbosity=2)
