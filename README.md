# healthbar
Circuit Python code for a physical health bar that syncs with D&amp;D Beyond to display character health.

## Features

- Connects to the D&D Beyond Maps VTT websocket and listens for character sheet changes.
- When it receives a websocket event it fetches the JSON character sheet.
- Parses the JSON character sheet and gets baseHitPoints, temporaryHitPoints, removedHitpoints, hitDice, and CON score to calculate current HP.
- Converts hitpoint fraction to decimal percentage and outputs percentage to Neopixels.

## Hardware

- Raspberry Pi Pico W running CircuitPython with `wifi`, `ssl`, and `socketpool`. Pico 2W with increased memory would run better.
- 2 x 8 NeoPixel strips on **`GP0`**.
- Pimoroni LiPo SHIM for Pico: https://shop.pimoroni.com/products/pico-lipo-shim?variant=32369543086163.
- 3.7v 2000mAh LiPo Battery

## Dependencies

CircuitPython libraries:

- `adafruit_requests`
- `neopixel` / Adafruit NeoPixel driver
- `adafruit_logging` (used by the bundled WebSocket client)
- My fork of **`cpwebsockets/`**, a CircuitPython WebSocket client. Couldn't use REGEX due to memory constraints.

## Configuration

Edit settings.toml with your Wi‑Fi credentials, D&D Beyond user id, character id, game id, and cookie.

## D&D Beyond IDs and Cookie

1. Open your character sheet in D&D Beyond. The character id is the number at the end of the URL.
2. "Inspect" the character sheet page. Go to the Network tab, reload the page, find the user id in the list of names.
3. Look through the list of requests under the Network tab for a JSON request that is your character id and may or may not include custom items ie {;} 1234567890?includeCustomItems=true
4. Open that request, copy everything from the cookie field in that request.
5. Create a new campaign, add your character. Create a new Maps session, add your character. The game id is the number at the end of the Maps VTT url.

| Variable | Purpose |
|----------|---------|
| `WIFI_SSID` / `WIFI_PASSWORD` | Network credentials |
| `GAME_ID` | Maps VTT game id |
| `USER_ID` | D&D Beyond user id |
| `CHARACTER_ID` | D&D Beyond character id |
| `COOKIE_HEADER` | `Cookie` header value for authenticated D&D Beyond requests |

## How HP is computed

`calculate_hp` calculates max HP from base HP, hit dice, CON modifier, and temporary HP, then current HP from removed HP, and returns current/max as a fraction for the bar.

## Running

Copy `code.py` (and `cpwebsockets/`) to the device, install any missing libraries under `lib/`, configure the environment variables, then reset the board.

## Disclaimer

This is an experimental proof of concept, not a finished product. This project talks to D&D Beyond using your account cookies, which may change. Use at your own risk. This is an unofficial hobby project and is not affiliated with Wizards of the Coast or D&D Beyond.
