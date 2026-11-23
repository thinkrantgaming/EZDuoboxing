# EZDuoboxing setup guide

This guide covers the script-only v4.9.1 release. Keep the complete folder together: sender and receiver scripts import shared files beside them. Extract a fresh copy instead of overwriting a working installation. Keep your personal configuration backups.

## 1. Decide which computer does what

- **Sender / local computer:** the Steam Deck or Windows PC with your physical controller and local character.
- **Receiver / remote computer:** another PC with another game client. It receives inputs and turns them into keyboard/mouse events or a virtual gamepad.
- Each additional remote computer runs its own receiver. A remote character need not use the same class, game key bindings, or output style as the local character.

Start with one receiver. Add a second after the first works. The remote game must be running and configured for the output type you choose. KBM events go to the foreground application. A virtual controller is a system device; it is not attached to a specific game window by this bridge.

Record the sender and receiver IPv4 addresses. Use `ipconfig` in Windows PowerShell, `hostname -I` on the Deck. Use the LAN address for your active Wi-Fi/Ethernet adapter, not loopback, VPN, or a disconnected adapter. Reserving addresses in your router avoids stale settings later. Both devices need to be able to reach each other; guest Wi-Fi may isolate them.

## 2. Install the scripts

Download the repository ZIP, extract it, and open a terminal in the extracted folder. Rename the folder to `EZDuoboxing` if convenient. The same folder can be used on all computers; install dependencies only for the role each machine runs.

### Windows prerequisites

Use 64-bit Python 3.14 to match the tested dependency choice. With the Python Install Manager:

```powershell
py install 3.14
py -3.14 --version
```

If `py install` is not recognized, install the manager or a Python 3.14 Windows installer from [python.org](https://www.python.org/downloads/windows/). See the [official Windows Python guide](https://docs.python.org/3.14/using/windows.html).

Always use `py -3.14` for both installation and execution. Plain `py` can pick a different version with different installed packages.

On a **Windows sender**:

```powershell
py -3.14 -m pip install --only-binary=:all: -r requirements-windows-sender.txt
```

On a **Windows receiver**:

```powershell
py -3.14 -m pip install --only-binary=:all: -r requirements-windows-receiver.txt
```

On a machine serving both roles at different times, install both. Do not run duplicate sender/receiver processes unintentionally.

### Steam Deck prerequisites and transfer

The Deck sender uses SteamOS's Python 3 standard library; no pip packages are needed. The full folder must include `deck_sender.py`, `sender_common.py`, `native_controls.py`, and your configuration.

In Desktop Mode, extract the ZIP to `/home/deck/EZDuoboxing`. To copy from Windows instead, optionally enable SSH from the Deck's Konsole:

```bash
passwd
sudo systemctl enable --now sshd
hostname -I
```

Then, from PowerShell in the directory containing your extracted EZDuoboxing folder:

```powershell
scp -r .\EZDuoboxing deck@DECK_IP:/home/deck/
ssh deck@DECK_IP
```

Replace `DECK_IP`. Enabling SSH is optional and persists across boots; use a password you control. Disable it later with `sudo systemctl disable --now sshd` if you no longer need it. Keep the Deck awake; sleep suspends the sender and network.

In the Deck terminal or SSH session:

```bash
cd ~/EZDuoboxing
python3 --version
python3 deck_sender.py --list
```

Run the game and Steam Input in Gaming Mode while testing actual controls. SSH can keep the sender terminal accessible without leaving the game. Disconnecting a terminal session can stop a foreground script; an optional service is described below.

## 3. Choose receiver output

### Keyboard/mouse only

No virtual-controller driver is needed. The default `receiver_config.py` is an example: A sends `1`, B holds Shift, left stick sends WASD, right stick moves the mouse. Change these to the game's actual binds; there is no need to use otherwise-unused punctuation keys on the local computer.

### Gamepad or mixed input on Windows

Two different components are required:

1. **ViGEmBus Windows driver:** install the official [1.22.0 release](https://github.com/nefarius/ViGEmBus/releases/tag/v1.22.0) on every gamepad-output receiver. Restart Windows if requested. This is the final archived release; the backend is optional and needs testing on your system.
2. **Python vgamepad package:** install into the same Python used by the receiver. Skip its bundled older driver installer because the driver was installed separately:

```powershell
$env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL = 'true'
py -3.14 -m pip install -r requirements-windows-gamepad.txt
```

Seeing “Nefarius Virtual Gamepad Emulation Bus” in Device Manager confirms the driver, not the Python package. [vgamepad API and installation reference](https://github.com/yannbouteiller/vgamepad).

Choose `receiver_config.gamepad.py` for direct standard-controller mapping or `receiver_config.mixed.py` for an example mixing gamepad and keyboard actions. Both can be selected using `--controls`. Extra grips/pad sectors have no direct Xbox equivalent; assign them explicitly if needed.

If playing through an emulator, bind the virtual Xbox controller to the intended player/controller port in the emulator. Launch the receiver before selecting it. Some games detect controllers only at startup.

## 4. Shared token and firewall

Sender and receiver must use the exact same token. The shipped `CHANGE_THIS_PRIVATE_TOKEN` value permits initial matching but is public; replace it for normal use. Generate a token, for example:

```powershell
py -3.14 -c "import secrets; print(secrets.token_hex(32))"
```

Copy the result into your sender's personal config and the receiver's `--token` argument. Do not generate different tokens independently on each computer. A token mismatch is silently rejected. Keep personal configs and tokens out of GitHub commits and screenshots.

The default port is **UDP 50505**. Open inbound UDP on the Windows receiver, scoped to the actual sender's IP. Run PowerShell as Administrator once, replacing `SENDER_IP`:

```powershell
New-NetFirewallRule -DisplayName "EZDuoboxing UDP 50505" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 50505 -RemoteAddress SENDER_IP -Profile Any
```

This allows that sender on whichever profile the adapter uses. If you change port or sender IP, update the rule. For another port, create a separate rule with that port/name. Ordinary LAN use does not need router port forwarding. See [Microsoft's firewall command reference](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule).

Remove the example rule if uninstalling:

```powershell
Remove-NetFirewallRule -DisplayName "EZDuoboxing UDP 50505"
```

## Steam Input: local and remote layers

**The sender does not block local input.** Native mode reads physical controls; Steam Input controls what the local game receives.

1. Keep your normal layer's local layout: gamepad, KBM, or a mixture.
2. On R5, bind **Hold Action Set Layer** for a layer named, for example, REMOTE_1.
3. In that layer, **replace** face-button, D-pad, bumper, Select/Start, stick-click and action-grip output commands with **Cleared from Parent**. Do not add a blank command alongside the old command. Check extra commands, subcommands, long/double presses, and chord bindings too.
4. Set stick and touchpad output behaviors to **Disabled** where available. For triggers, disable analog output and clear both soft/full-pull commands.
5. Preserve the selector's layer activation/release mechanism. Do not clear R5's hold-layer command itself.
6. For an L5 destination, create the equivalent L5-held layer. If you change selectors in `config.local.py`, change these layer activators to the SAME physical buttons.

“Cleared from Parent” prevents inherited local button output while the layer is active. It does not remove physical events from the native sender. Test A first: normal A should act locally, R5+A should act remotely without acting locally. Then test each stick, trigger and grip. Test switching layers with a stick already held and releasing it afterward.

A game/emulator reading physical HID directly can bypass Steam Input suppression. If outputs still occur after you confirm the correct layer is active and cleared, inspect its controller selection. EZDuoboxing does not hide or exclusively grab physical devices.

**Legacy Deck virtual input mode is different:** it reads Steam Input's virtual gamepad. Clearing its outputs also removes those inputs from the sender. Use `--input-source native` for the setup above. Steam Input macros/remaps on the sender are not forwarded in native mode.

## 5. First receiver launch

On the receiver laptop, in its EZDuoboxing directory:

```powershell
py -3.14 windows_receiver.py --sender-ip SENDER_IP --token "YOUR_SHARED_TOKEN"
```

For direct remote gamepad output:

```powershell
py -3.14 windows_receiver.py --sender-ip SENDER_IP --controls receiver_config.gamepad.py --token "YOUR_SHARED_TOKEN"
```

For mixed output, substitute `receiver_config.mixed.py`. `--sender-ip` always means the LOCAL computer with the controller, not the receiver's own IP. The old name `--deck-ip` remains an alias for compatibility, even for a Windows sender.

## 6. Sender probe, then live sending

### Built-in Steam Deck

Single receiver, default R5 selection:

```bash
python3 deck_sender.py RECEIVER_IP --input-source native --grips --touchpads pressure --token "YOUR_SHARED_TOKEN" --probe
```

Release both selectors once after starting/reconnecting. Hold R5 and press A or move a stick. Probe prints events and sends NO network packets. Stop with Ctrl+C. Remove `--probe` to begin forwarding:

```bash
python3 deck_sender.py RECEIVER_IP --input-source native --grips --touchpads pressure --token "YOUR_SHARED_TOKEN"
```

### Steam Controller 2026 attached to the Deck

Add `--controller steam` to those commands. USB, Bluetooth and puck use the same command; device discovery determines the path. Do not select the built-in Deck accidentally. `--list` shows hardware; `--debug-native` prints sampled reports for troubleshooting. Native mode does not depend on identifying the correct virtual Xbox device.

### Windows with Steam Controller 2026

Keep Steam running for local bindings/layers. The Windows sender reads native hardware directly:

```powershell
py -3.14 windows_sender.py --list
py -3.14 windows_sender.py RECEIVER_IP --token "YOUR_SHARED_TOKEN" --probe
```

Stop the probe, then:

```powershell
py -3.14 windows_sender.py RECEIVER_IP --token "YOUR_SHARED_TOKEN"
```

An initial HID error can be from a non-input interface. What matters is whether the correct interface attaches and remains responsive; repeated resets/missing inputs need troubleshooting.

## 7. Verify before playing

The receiver should show `Receiving sender input (connected/reconnected).` Heartbeats should produce this even when no selector is held. Seeing input on the sender alone is not proof of delivery.

For KBM, focus Notepad and use a binding such as A → `1`. For gamepad output, run `joy.cpl`, select the virtual Xbox controller, and inspect Properties. Hold the selector, press buttons, release it, and confirm neutral state. Then test the intended game/emulator.

Verify all of these:

- No selector: no remote actions.
- Selector held: matching remote actions and no unwanted local actions.
- Selector released: all remote held inputs released.
- Sender stopped or network interrupted: receiver releases inputs after its timeout (default one second).
- Reconnection: release selectors, then select a host again.

Use Ctrl+C to stop either script. Do not use a second copy of a receiver on the same port. Keep the receiver's intended KBM application focused; its terminal logs can be viewed without keeping it focused during gameplay.

## 8. Multiple receivers and custom selectors

Copy `config.py` to `config.local.py`, edit IPs/token, enable host2 if used, and run WITHOUT a positional receiver IP:

```bash
python3 deck_sender.py --config config.local.py
```

Windows sender:

```powershell
py -3.14 windows_sender.py --config config.local.py
```

The sample sets Deck native input, grips, and pressure touchpads. Receiver 1 uses R5, receiver 2 L5. Each receiver runs with its own controls file and the matching token/port. Separate PCs can all listen on UDP 50505. Detailed selector changes and the hold/release rules are in [CONFIGURATION.md](CONFIGURATION.md).

## 9. Optional macOS receiver

macOS supports KBM only. Use a separate environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-macos.txt
python macos_receiver.py --sender-ip SENDER_IP --token "YOUR_SHARED_TOKEN"
```

Enable the terminal (and Python if separately listed) in System Settings → Privacy & Security → Accessibility, then reopen it. Keep `windows_receiver.py`, `gamepad_output.py`, and `receiver_config.py` alongside the Mac receiver because they provide shared logic. No Windows-only package is imported for a KBM config. `--controls receiver.local.py` selects a custom file. Gamepad configs do not work on macOS.

## 10. Optional Deck auto-start

First confirm manual operation and native HID read permission. The sample service assumes `~/EZDuoboxing` and a working `config.local.py`:

```bash
mkdir -p ~/.config/systemd/user
cp examples/ezduoboxing-deck.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ezduoboxing-deck.service
journalctl --user -u ezduoboxing-deck.service -f
```

Edit the paths first if the folder is elsewhere. Add `--controller steam` to ExecStart for the external controller. This is a user-session service; it does not prevent sleep or guarantee availability before login. Stop it before launching a manual sender:

```bash
systemctl --user stop ezduoboxing-deck.service
```

Disable automatic startup with `systemctl --user disable --now ezduoboxing-deck.service`. It retries missing devices but cannot fix permissions. See [troubleshooting](TROUBLESHOOTING.md).
