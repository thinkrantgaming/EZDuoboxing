import runpy
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import native_controls as native
import deck_sender as deck
import windows_receiver as receiver
import gamepad_output

ZERO = dict(LX=0., LY=0., RX=0., RY=0.)
HOSTS = {'host1': dict(button='R5')}

def report(bits=0, axes=(0,0,0,0), triggers=(0,0)):
    raw = bytearray(64); raw[:4] = b'\x01\x00\x09\x3c'
    struct.pack_into('<I', raw, 8, bits)
    struct.pack_into('<HHhhhh', raw, 44, *triggers, *axes)
    return bytes(raw)

class NativeTests(unittest.TestCase):
    def test_deck_layout(self):
        state = native.NativeControls()
        for bit, name in ((7,'A'),(8,'DPAD_UP'),(11,'DPAD_DOWN'),(12,'BACK'),(14,'START'),(22,'L3'),(26,'R3')):
            state.update(report(1<<bit))
            self.assertEqual(state.buttons,{name})
        state.update(report(axes=(-32768,32767,32767,-32768), triggers=(32767,0)))
        self.assertEqual(state.axes,dict(LX=-1.,LY=-1.,RX=1.,RY=1.))
        self.assertEqual(state.buttons,{'LT'})
        state.update(report(triggers=(15000,32767)))
        self.assertEqual(state.buttons,{'LT','RT'})
        state.update(report(triggers=(0,0)))
        self.assertFalse(state.buttons)

    def test_native_without_virtual_and_timeout(self):
        reader = deck.GripReader(True)
        reader.physical.update(report(1<<7))
        reader.active_fd=1; reader.last_report=1
        reader.router.update(set()); reader.router.update({'R5'})
        snap=deck.routed_snapshots(reader.physical, reader, 1, HOSTS)['host1']
        self.assertEqual(snap['buttons'],['A'])
        self.assertTrue(snap['healer_active'])
        self.assertFalse(deck.routed_snapshots(reader.physical, reader, 2, HOSTS)['host1']['healer_active'])

    def test_native_edge_callback_reads_current_state(self):
        reader=deck.GripReader(True); reader.fds={123:'test'}
        snapshots=[]
        with patch.object(deck.os, 'read', side_effect=[report(),report((1<<16)|(1<<11)),BlockingIOError()]):
            reader.poll(1, lambda: snapshots.append(deck.routed_snapshots(reader.physical,reader,1,HOSTS)['host1']))
        self.assertEqual(snapshots[-1]['buttons'],['DPAD_DOWN'])

    def test_invalid_report_ignored(self):
        state=native.NativeControls()
        self.assertFalse(state.update(b'bad'))
        self.assertEqual(state.axes,ZERO)

class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.old=receiver.config
        self.config=SimpleNamespace(**runpy.run_path(str(Path(__file__).resolve().parents[1] / 'receiver_config.mixed.py')))
        receiver.config=self.config
        self.patch=patch.object(receiver,'GamepadOutput'); self.factory=self.patch.start()
        self.api=Mock();self.bridge=receiver.InputBridge(self.api);self.pad=self.factory.return_value
    def tearDown(self):
        receiver.config=self.old;self.patch.stop()

    def test_mix_and_release(self):
        self.bridge.update_state(['A','DPAD_DOWN'],dict(ZERO,LX=.5),1)
        self.pad.button.assert_called_with('A',True)
        self.api.keyDown.assert_called_with('s')
        self.bridge.release_all()
        self.pad.button.assert_called_with('A',False)
        self.api.keyUp.assert_called_with('s')
        self.pad.reset.assert_called_once()
        self.assertFalse(self.bridge.refs)

    def test_duplicate_target_and_tap_reference_counts(self):
        self.config.BINDINGS={'A':dict(mode='gamepad_hold',button='A'), 'B':dict(mode='gamepad_tap',button='A')}
        self.bridge.update_state(['A','B'],ZERO,1)
        self.bridge.tick(2,.01)
        self.pad.button.assert_called_once_with('A',True)
        self.bridge.update_state([],ZERO,2)
        self.pad.button.assert_called_with('A',False)

    def test_timeout_inactive_and_session_restart_neutralize(self):
        session=receiver.ReceiverSession(self.bridge)
        msg=dict(session='a',seq=1,buttons=['A'],axes=ZERO,healer_active=True)
        session.accept(msg,1)
        session.tick(3)
        self.assertFalse(self.bridge.refs)
        session.accept(dict(msg,seq=2),4)
        session.accept(dict(msg,seq=3,healer_active=False),4.1)
        self.assertFalse(self.bridge.refs)
        session.accept(dict(msg,seq=4),5)
        session.accept(dict(msg,session='b',buttons=[]),5.1)
        self.assertFalse(self.bridge.refs)
        self.assertGreaterEqual(self.pad.reset.call_count,4)

    def test_validation(self):
        receiver.validate_config()
        self.config.BINDINGS['A']['button']='NOPE'
        with self.assertRaises(ValueError): receiver.validate_config()
        self.config.BINDINGS['A']['button']='A'
        self.config.LEFT_STICK_ENABLED=True
        with self.assertRaises(ValueError): receiver.validate_config()

    def test_adapter_axes_triggers_and_reset(self):
        module=Mock();adapter=gamepad_output.GamepadOutput(module)
        adapter.axes(dict(LX=.5,LY=-.75,RX=-1,RY=1),True,True)
        module.VX360Gamepad.return_value.left_joystick_float.assert_called_with(x_value_float=.5,y_value_float=.75)
        adapter.button('RT',True)
        module.VX360Gamepad.return_value.right_trigger.assert_called_with(value=255)
        adapter.button('RT',False)
        module.VX360Gamepad.return_value.right_trigger.assert_called_with(value=0)
        adapter.reset()
        module.VX360Gamepad.return_value.reset.assert_called_once()

if __name__=='__main__': unittest.main()
