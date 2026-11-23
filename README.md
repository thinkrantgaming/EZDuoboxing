# EZDuoboxing

**Use a Steam Deck or Steam Controller to control your local game and selectively forward input to another computer.** Hold a configured selector to control one remote character; release it to return to local play.

Designed for multi-character MMORPG setups, with independent keyboard/mouse, gamepad, or mixed mappings on each receiver. Compatibility depends on the game or emulator accepting those inputs. Check the rules of the game/server you play on; this project does not establish permission to use input forwarding.

**Version 4.9.1 · Python scripts · No GUI required**

```text
Steam Deck / Windows + Steam Controller
             │
             ├─ No selector held → local Steam Input layout
             ├─ Hold R5          → receiver 1
             └─ Hold L5          → receiver 2 (optional)
```

R5/L5 are defaults, not requirements. Assign supported buttons such as LB, BACK, or a D-pad direction in `config.local.py`. [Configure selectors and mappings →](docs/CONFIGURATION.md)

## Start here

1. **[Complete setup guide](docs/SETUP.md)** — prerequisites, installation, Steam Input layers, networking, and first test.
2. **[Controls and configuration](docs/CONFIGURATION.md)** — change selectors, keys, buttons, sticks, and touchpads.
3. **[Troubleshooting](docs/TROUBLESHOOTING.md)** — local input leaks, no remote input, Python dependencies, controller reads, and stuck keys.
4. **[Architecture and limitations](docs/ARCHITECTURE.md)** — routing behavior, protocol, hardware support, and validation status.
5. **[GitHub publishing](docs/PUBLISHING.md)** — upload this repository and create a release.

## Supported combinations

| Role | System | Input/output |
|---|---|---|
| Sender | Steam Deck / SteamOS | Built-in Deck; native physical input or legacy virtual Xbox input |
| Sender | Steam Deck / SteamOS | Steam Controller 2026 with `--controller steam` |
| Sender | Windows 10/11 | Steam Controller 2026 native HID input |
| Receiver | Windows 10/11 | Keyboard/mouse, virtual Xbox 360 gamepad, or mixed |
| Receiver | macOS | Keyboard/mouse only; Accessibility permission required |

USB, Bluetooth and wireless-puck report handling is implemented for the 2026 Steam Controller. Not every transport/firmware combination has been physically verified. The original 2015 Steam Controller and arbitrary controllers are not supported sender devices in this release. macOS/Linux gamepad receivers are not included.

## What it does

- Selects **one remote destination at a time**, with configurable hold selectors.
- Preserves remote modifier chords, held buttons, touchpad sectors, and continuous stick movement.
- Reconnects after input-device/network errors and releases remote inputs on route loss or timeout.
- Supports different mappings on each receiver: e.g. D-pad Up → D-pad Up on one PC, D-pad Up → `w` on another.
- Keeps the same network protocol as the earlier v4.9 scripts.

**Local suppression is configured in Steam Input.** The sender does not automatically block the local game. Use native input mode and clear local outputs in your selector-held layers. [Exact setup →](docs/SETUP.md#steam-input-local-and-remote-layers)

## Short example

After installation and Steam Input setup, on the receiver:

```powershell
py -3.14 windows_receiver.py --sender-ip SENDER_IP --token "YOUR_SHARED_TOKEN"
```

On the Deck (replace placeholders):

```bash
python3 deck_sender.py RECEIVER_IP --input-source native --grips --touchpads pressure --token "YOUR_SHARED_TOKEN"
```

Or on a Windows sender:

```powershell
py -3.14 windows_sender.py RECEIVER_IP --token "YOUR_SHARED_TOKEN"
```

These positional-IP sender commands use R5 and one receiver. For other selectors or multiple destinations, use `--config config.local.py` **without a positional IP**.

## Receiver templates

| File | Behavior |
|---|---|
| `receiver_config.py` | Keyboard/mouse example; default when `--controls` is omitted |
| `receiver_config.gamepad.py` | Standard buttons map directly; both sticks output analog gamepad movement |
| `receiver_config.mixed.py` | Gamepad controls except D-pad Down → `s`, L4 → Shift+1 |

Select a template with `--controls FILE`. Make personal copies ending in `.local.py`; Git ignores these. Gamepad output needs both the Python `vgamepad` package and the optional Windows ViGEmBus driver. Triggers are full press/release, not progressive analog output.

## Status

Automated tests use synthetic reports and mock input APIs. Real device/game testing is still necessary, especially for new native Deck layouts, virtual-gamepad output, and Steam Controller transport variants. No guarantee of universal MMORPG compatibility, precise macro timing, or atomic network handoff is made. Timed sequences, rumble feedback, and automatic Steam Input editing are not implemented.

See [CHANGELOG](CHANGELOG.md), [CONTRIBUTING](CONTRIBUTING.md), [SECURITY](SECURITY.md), and [third-party references](THIRD_PARTY_NOTICES.md).
