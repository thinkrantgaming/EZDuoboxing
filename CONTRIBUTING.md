# Contributing

Report reproducible problems using the issue templates. Include controller generation, connection type, sender/receiver OS, Python version, input source and output mode. Remove tokens and personal details from logs/configs.

## Development checks

Run from the repository root on Linux or macOS:

```bash
python3 -m compileall -q .
python3 -m unittest discover -s tests -v
```

The complete suite imports Linux/Unix `fcntl` through the Deck sender, so it does not run unchanged on native Windows. It uses no installed HID/gamepad/Quartz libraries for its mocked cases. The GitHub Actions workflow uses Linux and Python 3.11/3.14.

Useful Windows-focused tests can be run on Windows with:

```powershell
py -3.14 -m unittest discover -s tests -p test_windows_sender.py -v
```

These simulate HID; they are not physical hardware qualification.

## Change expectations

- Preserve sender routing, selector consumption, all-release rearm, and inactive/timeout cleanup.
- Do not enqueue stale gameplay commands for replay after reconnect.
- Keep existing configs working unless a migration is explicit.
- Avoid importing platform-only dependencies at module import when core logic can remain testable.
- New output kinds need held/tap/refcount/timeout/stop tests.
- New physical reports need source references, bounds checks, fixtures and actual-device evidence when available.
- Document whether tests are simulated or hardware-based.
- Do not commit private configs, account tokens, driver binaries or game files.

Submit small changes with the concrete problem, resulting behavior, tests, and compatibility implications. See LICENSING.md before contributing or redistributing.
