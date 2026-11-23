"""Optional Windows virtual Xbox 360 output. Imported only when configured."""
BUTTONS = {name: 'XUSB_GAMEPAD_' + suffix for name, suffix in {
    'A': 'A', 'B': 'B', 'X': 'X', 'Y': 'Y', 'BACK': 'BACK', 'START': 'START',
    'LB': 'LEFT_SHOULDER', 'RB': 'RIGHT_SHOULDER', 'L3': 'LEFT_THUMB', 'R3': 'RIGHT_THUMB',
    'DPAD_UP': 'DPAD_UP', 'DPAD_DOWN': 'DPAD_DOWN', 'DPAD_LEFT': 'DPAD_LEFT', 'DPAD_RIGHT': 'DPAD_RIGHT',
}.items()}
TARGETS = set(BUTTONS) | {'LT', 'RT'}


def needed(config):
    return (any(b.get('mode', '').startswith('gamepad_') for b in config.BINDINGS.values())
            or getattr(config, 'GAMEPAD_LEFT_STICK', False) or getattr(config, 'GAMEPAD_RIGHT_STICK', False))


class GamepadOutput:
    def __init__(self, module=None):
        if module is None:
            import sys
            if sys.platform != 'win32': raise RuntimeError('Gamepad output requires the Windows receiver.')
            try:
                import vgamepad as module
            except ImportError as exc:
                raise RuntimeError('Gamepad output needs vgamepad and ViGEmBus. See docs/SETUP.md.') from exc
        self.module = module
        try: self.pad = module.VX360Gamepad()
        except Exception as exc:
            raise RuntimeError('Cannot create virtual controller. Install ViGEmBus and restart Windows. See docs/SETUP.md.') from exc

    def button(self, name, pressed):
        if name in ('LT', 'RT'):
            method = self.pad.left_trigger if name == 'LT' else self.pad.right_trigger
            method(value=255 if pressed else 0)
        else:
            method = self.pad.press_button if pressed else self.pad.release_button
            method(button=getattr(self.module.XUSB_BUTTON, BUTTONS[name]))
        self.pad.update()

    def axes(self, axes, left, right):
        axes = {k: max(-1., min(1., v)) for k, v in axes.items()}
        if left: self.pad.left_joystick_float(x_value_float=axes['LX'], y_value_float=-axes['LY'])
        if right: self.pad.right_joystick_float(x_value_float=axes['RX'], y_value_float=-axes['RY'])
        self.pad.update()

    def reset(self):
        self.pad.reset()
        self.pad.update()
