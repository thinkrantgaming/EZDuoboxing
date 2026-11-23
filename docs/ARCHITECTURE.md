# Architecture, compatibility and limitations

## Components

| File | Responsibility |
|---|---|
| `deck_sender.py` | SteamOS device discovery, read-only hidraw/legacy evdev, routing and forwarding |
| `native_controls.py` | Deck and 2026 Steam Controller physical button/stick decoding |
| `windows_sender.py` | Windows read-only HIDAPI controller reading and forwarding |
| `sender_common.py` | Routing, touchpad sectors, config loading, authenticated packets, UDP retries |
| `windows_receiver.py` | Shared receiver/session/watchdog and KBM/gamepad action engine; Windows entry point |
| `gamepad_output.py` | Optional Windows virtual Xbox adapter through vgamepad |
| `macos_receiver.py` | Quartz KBM adapter and macOS entry point |
| `config.py` | Public sender template |
| `receiver_config*.py` | Public receiver templates |
| `tests/` | Synthetic reports, mock input APIs, protocol and routing checks |

Receiver configuration is intentionally independent from Steam Input. Physical input names become network actions; the selected receiver decides their output type. No remote screen/video, login, game launch, or game memory access is involved.

## Native and virtual input

Deck native mode reads controller reports through Linux hidraw. Standard controls and sticks come from `NativeControls`; grip/pad/routing logic uses the same physical reports. It works without a Steam Input virtual Xbox device. Default legacy virtual mode reads ordinary controls through evdev while native reports gate routing and provide extra grips/pads. Existing configs without INPUT_SOURCE retain virtual behavior; the new public sample selects native explicitly.

Windows reads native Steam Controller reports through hidapi. It does not use Steam Input's output mappings, send HID feature writes, change controller firmware settings, or hide physical devices. Steam remains responsible for the local layout and suppression layers.

Controller IDs/report layouts implemented:

- Valve vendor `28de`, built-in Deck product `1205`.
- 2026 Steam Controller products `1302`, `1303`, `1304`, `1305`.
- Deck 64-byte state report type 9; controller report IDs `42`, `45`, `47` with 46–64 bytes, plus disconnect status reports.

USB/Bluetooth/puck support is based on recognized layouts, not proof that every firmware/interface has been tested. Wrong interfaces can fail reads; the sender retries discovery. Original 2015 controller reports are not supported.

Protocol layout references: [SDL Deck driver](https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/SDL_hidapi_steamdeck.c), [SDL controller structures](https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/steam/controller_structs.h), and [SDL Triton driver](https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/SDL_hidapi_steam_triton.c).

## Wire format and lifecycle

The wire remains version 4. Each UDP datagram is `hex_hmac_sha256|json_body`. The JSON includes version, random session ID, increasing sequence number, physical buttons, four stick axes, and the legacy `healer_active` Boolean. That field means “this receiver is currently selected”; its old name is retained strictly for backward compatibility, not product branding.

The sender sends state on button transitions and approximately 30 times per second for axes/heartbeats. Unselected destinations receive neutral snapshots. Neutral destinations are sent before the active destination, but packet delivery/order is not guaranteed. There is no network acknowledgment: “sending resumed” means the local socket succeeded, not proof that a receiver accepted input.

Receivers check source IPv4, HMAC, version/types and sequence. A new session releases old input; previously retired sessions are rejected within a bounded in-memory history. Link timeout releases keys, mouse, gamepad buttons and axes. This is not a durable replay-prevention system across receiver restarts.

Native stale reports disable forwarding after roughly half a second. The receiver link watchdog defaults to one second. Reconnection requires selectors to be released before routing arms again. Network retries do not deliberately queue and replay old gameplay input.

## Output engine

KBM uses held reference counts, scheduled short taps, stick-to-key hysteresis, and relative mouse movement. Gamepad targets share reference-counted holds/taps and reset on route loss, timeout, sender-session changes, or clean shutdown. The vgamepad dependency is loaded only when a gamepad config requires it. A virtual Xbox controller lasts while its receiver instance is alive.

Sticks are analog for gamepad output. Triggers are digital full press/release in this release. No force-feedback return channel, progressive trigger passthrough, automatic Steam Input configuration, or timed multi-step macro runner is provided. A key list is a chord. Touchpad sectors are additional named actions, not native Xbox touch surfaces.

## Trust and deployment

Use a trusted LAN and unique token. HMAC authenticates packets; it does not encrypt button state, make the local default token secret, or prevent every replay/denial-of-service scenario. The service is not designed for direct public-Internet exposure. Python config files execute code. Keep private `.local.py` files out of version control and load only your own trusted files.

One receiver process normally controls a foreground game/app on one OS. Two separate Windows PCs are straightforward. A VM needs its own reachable IP/port and game/input configuration. Host/guest focus and device forwarding can complicate isolation. Multiple receiver processes on one desktop do not provide reliable per-game input isolation.

## Validation status

The automated suite runs on Unix because Deck modules import `fcntl`. It simulates controller packets, HID APIs and injected input; it does not load Windows/macOS drivers in CI. Windows execution needs real hardware checks; macOS/SteamOS permissions and game compatibility also need actual-device testing.

v4.9.1 extends physical routing selectors beyond rear grips. New tests exercise accepted selector configs, standard Windows selectors, Deck native selection, trigger selection, opposite-selector actions, and release lockout. Earlier tests cover reconnect, touchpads, key refcounts and mixed output. See the CI workflow and CONTRIBUTING.md for reproducible checks.
