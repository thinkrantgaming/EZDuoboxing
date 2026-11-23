# Dependencies and protocol references

This repository does not vendor game files, Steam software, Python packages or driver binaries. Installed dependencies retain their own licenses and distribution conditions; the project license, if added, does not relicense them.

| Component | Use | Upstream |
|---|---|---|
| Python | Runtime/standard library | https://www.python.org/ |
| hidapi Python binding | Windows native controller reads | https://github.com/trezor/cython-hidapi |
| PyDirectInput | Windows keyboard/mouse injection | https://github.com/learncodebygaming/pydirectinput |
| vgamepad | Optional Windows virtual controller API | https://github.com/yannbouteiller/vgamepad |
| ViGEmBus | Optional Windows virtual-controller driver | https://github.com/nefarius/ViGEmBus |
| PyObjC Quartz | Optional macOS keyboard/mouse events | https://github.com/ronaldoussoren/pyobjc |

Physical report field layouts and button identifiers were checked against SDL's Steam Deck/Triton driver and controller structures:

- https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/SDL_hidapi_steamdeck.c
- https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/SDL_hidapi_steam_triton.c
- https://github.com/libsdl-org/SDL/blob/main/src/joystick/hidapi/steam/controller_structs.h

SDL is a protocol reference here; it is not a runtime dependency and its driver sources are not distributed in this repository. This Python implementation is not an official Valve or SDL product. Steam, Steam Deck, Steam Controller, Windows, Xbox and macOS are names belonging to their respective owners; no affiliation or endorsement is implied.
