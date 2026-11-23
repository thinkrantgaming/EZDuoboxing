# Changelog

## 4.9.1 — 2026-11-23

- Prepared the latest script-based implementation as EZDuoboxing, with game-neutral naming and complete setup documentation.
- Extended physical routing selectors from rear grips to supported standard buttons, D-pad directions and triggers on both senders. The active selector is consumed; opposite-selector actions and all-release lockout are preserved.
- Added receiver `--sender-ip` as a clearer alias for `--deck-ip`.
- Added macOS `--controls` selection for trusted KBM config files.
- Retained native Deck input, Windows native Steam Controller input, multiple destinations, reconnect/watchdog cleanup, touchpad sectors and configurable receiver mappings.
- Retained optional Windows virtual Xbox gamepad output and analog sticks. Triggers remain full press/release.
- Included clean KBM, gamepad and mixed templates, a custom-selector example, and optional Deck user service.
- Added repository hygiene, issue/PR templates, Linux CI, architecture/security notes and publishing instructions. No GUI/build scripts or personal configuration are distributed.
- Validation: 130 automated tests passed on the development Mac. Driver behavior and game/device compatibility still require hardware testing; GitHub CI runs after publication.

## 4.9 script baseline

Native Deck physical controls independent of Steam Input output; per-binding virtual Xbox or KBM output; default/optional gamepad and mixed templates; existing wire-v4 compatibility and timeout cleanup. The new package preserves those features while documenting their limits.
