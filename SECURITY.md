# Security and trust model

EZDuoboxing intentionally generates input on a remote computer. Use it only with computers and applications you control.

- Use a unique token instead of the public sample token, and scope the receiver's firewall rule to the sender IP.
- Keep the bridge on a trusted LAN. HMAC authenticates packet contents but does not encrypt them; this is not a public-Internet remote-access service.
- Source-IP checks and session sequence checks reduce accidental/old input, but do not provide durable replay prevention across receiver restarts or denial-of-service protection.
- Python controls/config files execute code. Never load an unreviewed config from an untrusted source, especially as administrator/root.
- Keyboard/mouse output reaches the foreground application; virtual gamepads are visible to the OS and potentially multiple applications.
- Prefer narrowly scoped device permissions. No broad HID permission changes or automatic driver installation are performed by the scripts.
- The optional ViGEmBus backend uses an archived driver; obtain it from its official repository and evaluate suitability for your Windows environment.

For a vulnerability, use the repository owner's private security reporting channel if enabled. Do not post tokens, personal network details or weaponized reproduction data in public issues. The repository owner should configure a private contact/reporting method before public release; none is invented by this template.

If a token is exposed, replace it on all affected senders/receivers. Removing it from the latest commit does not remove it from Git history.
