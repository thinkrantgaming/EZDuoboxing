# Troubleshooting

Work in this order: physical controller → sender probe → network/receiver connection → receiver output → game/emulator. A working earlier stage does not prove the next one works.

## Local character also moves

Confirm Deck startup says `Input source: native`. In the selector-held Steam Input layer, replace button outputs with **Cleared from Parent** and disable stick/touchpad/trigger outputs. Check extra commands and inherited bindings. Preserve the hold-layer selector itself. Verify the correct game/emulator layout is selected.

The sender does not automatically block local input. If a fully cleared active layer still produces local actions, the game/emulator may read the physical device directly. Inspect which device it uses. Native mode forwards physical labels; Steam Input remaps are not part of that stream.

## Sender prints events; receiver prints nothing

- Remove `--probe` to actually send.
- Sender destination must be the receiver's current LAN IPv4 address.
- Receiver `--sender-ip`/`--deck-ip` must be the MAIN sender's IP, not the receiver or a previous Deck address.
- Match token and UDP port exactly. IP/token rejection is silent.
- The receiver should print a connected message from neutral heartbeats even without a held selector.
- Positional-IP sender commands ignore config.py; use `--config config.local.py` alone for configured hosts/tokens/selectors.
- Check the receiver's UDP firewall rule, Wi-Fi isolation, VPNs, and active network adapter. A TCP `Test-NetConnection -Port` result does not test this UDP protocol.
- Run only one receiver process per listening port.

## ModuleNotFoundError: vgamepad

The Windows driver and Python package are separate. A driver in Device Manager does not install the Python package:

```powershell
$env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL = 'true'
py -3.14 -m pip install -r requirements-windows-gamepad.txt
py -3.14 windows_receiver.py --sender-ip SENDER_IP --controls receiver_config.gamepad.py --token "YOUR_SHARED_TOKEN"
```

Use the same Python version in both commands. If creating the controller still fails, confirm the official ViGEmBus driver is installed and restart Windows if its installer requested it.

## hidapi tries to compile / requests C++ Build Tools

A Python version without a matching wheel may cause a source build. Use the documented 64-bit Python 3.14 environment:

```powershell
py install 3.14
py -3.14 -m pip install --only-binary=:all: -r requirements-windows-sender.txt
```

The dependency is named `hidapi`, while the Python import is `hid`. A different package named `hid` is not a substitute. Keep `py -3.14` in your sender command.

## Initial HID read errors, then working input

The Windows sender can encounter non-input interfaces before finding state reports. If a native interface attaches and input remains reliable, those initial failures may be from unused interfaces. Repeated disconnect/reconnect messages or missing input are not normal success.

Capture diagnostics:

```powershell
py -3.14 windows_sender.py --list
py -3.14 windows_sender.py RECEIVER_IP --probe --debug-native
```

Record USB/Bluetooth/puck connection type. Temporarily exiting Steam is a diagnostic for shared-device access, not the intended playing configuration: local Steam Input bindings need Steam. After discovering the correct path, `--hid-path "EXACT_PATH_FROM_LIST"` can restrict Windows reading. Recheck after reconnecting because paths can change.

## Deck: no readable native device

```bash
python3 deck_sender.py --list
```

Use the correct controller choice: built-in Deck or `--controller steam`. Native mode requires the corresponding `/dev/hidrawN` readable by the user running the script. Inspect the listed error before changing permissions.

For a temporary, narrowly scoped permission test, identify the EXACT controller path from the list, then on SteamOS where `setfacl` is available:

```bash
sudo setfacl -m u:deck:r /dev/hidrawN
```

Replace N with that device's number and `deck` if using another account. This is not a persistent solution; reconnect/reboot can recreate the node. Do not grant world-write access to all HID devices or run unreviewed custom Python configs as root. A persistent rule should match the specific controller and local user/session policy. Report the device/vendor/product and permission error when asking for help.

`--grip-device /dev/hidrawN` selects a Deck/Linux native path explicitly. For legacy virtual mode only, `--device /dev/input/eventN` chooses the virtual Xbox device. Native mode does not require an evdev virtual device.

## R5/L5 or custom selector does nothing

Release all selectors after startup or reconnect. If multiple selectors were held together, release them all before trying again. Confirm `button` names are valid and unique, the host is enabled, and your launch uses `--config` without a positional IP. Update Steam Input hold-layer activators to match new selectors. A held opposite selector acts on the current host; it does not switch hosts until the current selector and all others are released.

## R5+D-pad sends keys instead of gamepad

The default receiver config is a KBM example. Explicitly choose:

```powershell
py -3.14 windows_receiver.py --sender-ip SENDER_IP --controls receiver_config.gamepad.py --token "YOUR_SHARED_TOKEN"
```

For your own file, use `gamepad_hold` with `button`, not `hold` with `keys`. Restart after editing. The remote game or emulator must use the virtual Xbox controller; run `joy.cpl` to verify its output independently of the game.

## Input arrives, but game ignores it

Focus the intended game for KBM; first test text in Notepad. Check its own key bindings and keyboard layout. Games running elevated may require the receiver to run at matching privilege. Some games reject injected keyboard/mouse events. This cannot be solved just by changing the network port.

For gamepad output, start the receiver before the game, choose the virtual Xbox device in game/emulator settings, and avoid accidentally selecting the physical controller or another virtual device. Steam Input on the receiver may apply another remapping layer. Test direct output first. Mixed keyboard/gamepad mode switching depends on the game.

## Stuck movement / modifiers

Release selectors and stop the sender. The receiver watchdog should release input within LINK_TIMEOUT_SECONDS (default one second). Ctrl+C on the receiver runs cleanup. Local stuck movement is separate: inspect Steam Input layer transitions, especially changing layers with sticks/keys already held. The bridge cannot release keys held by an unrelated local application.

If only certain keys stick, remove duplicate/conflicting mappings and test the smallest config. Preserve logs and the exact sequence of button presses/releases.

## Touchpads inaccurate or too sensitive

Use native pressure mode and disable their local Steam Input output in remote layers. Test `--probe --touchpads pressure --debug-touchpads`. Down/up log lines mean press/release, not opposite directions. The chosen sector is latched until release. Change pressure thresholds only after reading raw values; your hardware may need different thresholds.

## Old EXE says python314.dll is missing

This repository is scripts only. Run the documented Python command; there is no EXE build here. An older GUI build's intermediate `build/` executable is not standalone. Use its complete `dist/` folder if maintaining that separate version. This release does not repair or distribute that GUI.

## SSH stopped working

On the Deck's Konsole, check:

```bash
sudo systemctl enable --now sshd
sudo systemctl restart sshd
systemctl is-active sshd
hostname -I
```

Use the current address, keep the Deck awake, and check both machines are on a reachable network. An IP reservation reduces address changes. SSH availability and the bridge's UDP connection are separate.

## Report a problem

Use the repository bug-report template. Include version, OS/Python, connection type, sender input source, output style, command lines with tokens removed, and whether probe/Notepad/joy.cpl work. Tests cannot substitute for actual hardware reports.
