import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import deck_sender
import windows_sender
import sender_common
from native_controls import DECK_BITS
from test_mixed_input import report as deck_report
from test_windows_sender import report as steam_report

class CustomSelectorTests(unittest.TestCase):
    def test_config_accepts_every_supported_selector(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.py'
            for button in sender_common.SELECTOR_BUTTONS:
                path.write_text('HOSTS='+repr({'remote':dict(ip='192.0.2.1',button=button)}))
                self.assertEqual(sender_common.load_hosts(path)[0]['remote']['button'],button)

    def test_deck_bumper_selects_and_is_consumed_without_virtual_input(self):
        hosts={'remote':dict(button='LB')}
        reader=deck_sender.GripReader(True,routes={'remote':'LB'})
        reader.fds={123:'test'}
        states=[]
        with patch.object(deck_sender.os,'read',side_effect=[deck_report(),deck_report((1<<3)|(1<<7)),BlockingIOError()]):
            reader.poll(1,lambda: states.append(deck_sender.routed_snapshots(reader.physical,reader,1,hosts)['remote']))
        self.assertEqual(states[-1]['buttons'],['A'])
        self.assertTrue(states[-1]['healer_active'])

    def test_windows_standard_selectors_and_startup_lockout(self):
        for bit,button in windows_sender.BUTTON_BITS.items():
            with self.subTest(button=button):
                hosts={'remote':dict(button=button)}
                state=windows_sender.ControllerState(hosts)
                state.update(steam_report(1<<bit),1)
                self.assertFalse(state.snapshots(1)['remote']['healer_active'])
                state.update(steam_report(),2)
                state.update(steam_report(1<<bit),2.1)
                snapshot=state.snapshots(2.1)['remote']
                self.assertTrue(snapshot['healer_active'])
                self.assertNotIn(button,snapshot['buttons'])
                state.update(steam_report(),2.2)
                self.assertFalse(state.snapshots(2.2)['remote']['healer_active'])

    def test_trigger_selector_and_opposite_selector_action(self):
        hosts={'first':dict(button='LT'),'second':dict(button='BACK')}
        state=windows_sender.ControllerState(hosts)
        state.update(steam_report(),1)
        state.update(steam_report(triggers=(32767,0)),1.1)
        self.assertTrue(state.snapshots(1.1)['first']['healer_active'])
        state.update(steam_report(1<<14,triggers=(32767,0)),1.2)
        self.assertIn('BACK',state.snapshots(1.2)['first']['buttons'])
        state.update(steam_report(1<<14),1.3)
        self.assertTrue(all(not s['healer_active'] for s in state.snapshots(1.3).values()))
        state.update(steam_report(),1.4)
        state.update(steam_report(1<<14),1.5)
        self.assertTrue(state.snapshots(1.5)['second']['healer_active'])

if __name__=='__main__': unittest.main()
