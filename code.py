import os
import errno
import gc
import json
import time
import board
import neopixel
import wifi
import ssl
import socketpool
import adafruit_requests
import cpwebsockets.client

import traceback

# Get config from settings.toml
WIFI_SSID = os.getenv("WIFI_SSID")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD")

GAME_ID = os.getenv("GAME_ID")
USER_ID = os.getenv("USER_ID")
CHARACTER_ID = os.getenv("CHARACTER_ID")

AUTH_URL = "https://auth-service.dndbeyond.com/v1/cobalt-token"
WS_BASE = "wss://game-log-api-live.dndbeyond.com/v1"
CHARACTER_URL = "https://character-service.dndbeyond.com/character/v5/character/"

ORIGIN = "https://www.dndbeyond.com"
REFERER = "https://www.dndbeyond.com"

COOKIE_HEADER = os.getenv("COOKIE_HEADER")

# Update this to match your number of Neopixels
num_pixels = 16

pixels = neopixel.NeoPixel(board.GP0, num_pixels, auto_write=False)
pixels.brightness = 0.5

# Connect to wifi and print to console
def connect_wifi():
    print("Connecting Wi-Fi...")
    wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    print("Wi-Fi connected:", wifi.radio.ipv4_address)

# Build the websocket url, takes in the token from get_token
def build_ws_url(token):
    return (
        WS_BASE
        + "?gameId=" + str(GAME_ID)
        + "&userId=" + str(USER_ID)
        + "&stt=" + token
    )

# Gets the token from the auth url using the cookie
def get_token(session):
    headers = {
        "Accept": "*/*",
        "Origin": ORIGIN,
        "Referer": REFERER,
        "Cookie": COOKIE_HEADER,
    }
    resp = session.get(AUTH_URL, headers=headers, timeout=15)
    data = resp.json()
    resp.close()
    token = data["token"]
    ttl = int(data.get("ttl", 300))
    return token, ttl

# Keys we need from the JSON
_CHARACTER_KEYS = (
    "baseHitPoints",
    "removedHitPoints",
    "temporaryHitPoints",
    "hitDice",
)

# Gets the character json from the character API using the token
def get_character(session, token):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": ORIGIN,
        "Referer": REFERER,
        "Cookie": COOKIE_HEADER,
        "Authorization": "Bearer " + token,
        "Connection": "close",
    }

    # Chunk size for parsing stream
    # Tail to check if needle is split across chunks
    TAIL_BYTES = 256
    CHUNK_SIZE = 512

    gc.collect()
    resp = session.get(
        CHARACTER_URL + CHARACTER_ID,
        headers=headers,
        timeout=15,
        stream=True,
    )
    found = {}
    carry = b""
    total_read = 0
    try:
        stream = resp.iter_content(chunk_size=CHUNK_SIZE)
        print("started stream")
        for chunk in stream:
            if not chunk:
                break
            total_read += len(chunk)
            window = carry + chunk
            text = window.decode("utf-8", "ignore")
            for key in _CHARACTER_KEYS:
                if key in found:
                    continue
                val = extract_json(text, key, None)
                if val is not None:
                    found[key] = val
                    print("found ", key)
            if "conScore" not in found:
                con = extract_con(text)
                if con is not None:
                    found["conScore"] = con
                    print("found  conScore")
            if len(found) == len(_CHARACTER_KEYS) + 1:
                break
            if total_read > 50000:
                break
            if len(window) > TAIL_BYTES:
                carry = window[-TAIL_BYTES:]
            else:
                carry = window
        # Drain socket after finding keys
        for _chunk in stream:
            pass
    finally:
        resp.close()
        gc.collect()

    print("finished stream")

    return {
        "baseHitPoints": int(found.get("baseHitPoints") or 0),
        "removedHitPoints": int(found.get("removedHitPoints") or 0),
        "temporaryHitPoints": int(found.get("temporaryHitPoints") or 0),
        "hitDice": int(found.get("hitDice") or 0),
        "conScore": int(found.get("conScore") or 0)
    }

# Extracts json values without reading as json
def extract_json(raw, key, default=None):
    needle = '"' + key + '":'
    i = raw.find(needle)
    if i < 0:
        return default
    i += len(needle)

    # Skip whitespaces
    while i < len(raw) and raw[i] in " \t\r\n":
        i += 1
    if i >= len(raw):
        return default
    j = i
    # Find the next comma or curly brace
    while j < len(raw) and raw[j] not in ",}":
        j += 1
    token = raw[i:j].strip()
    if not token:
        return default
    try:
        return int(token)
    except ValueError:
        return default

# Extract CON score from nested array
def extract_con(text, default=None):
    needle = '"id":3,'
    pos = -1
    pos = text.find(needle)
    if pos < 0:
        return None

    tail = text[pos : pos + 50]
    vneedle = '"value":'
    j = tail.find(vneedle)
    if j < 0:
        return None
    j += len(vneedle)
    while j < len(tail) and tail[j] in " \t\r\n":
        j += 1
    if j >= len(tail):
        return None
    k = j
    while k < len(tail) and tail[k] not in ",}\n\r":
        k += 1
    try:
        return int(tail[j:k].strip())
    except Exception:
        return None

# Checks message from websocket and determines if it should get_character
def should_refresh_character(evt):
    if evt.get("eventType") != "character-sheet/character-update/fulfilled":
        return False
    if evt.get("entityType") != "character":
        return False

    entity_id = str(evt.get("entityId", ""))
    data_character_id = str((evt.get("data") or {}).get("characterId", ""))
    return entity_id == str(CHARACTER_ID) or data_character_id == str(CHARACTER_ID)

# Calculates hitpoints from character json
def calculate_hp(character_data):
    base_hp = int(character_data.get("baseHitPoints") or 0)
    removed_hp = int(character_data.get("removedHitPoints") or 0)
    temp_hp = int(character_data.get("temporaryHitPoints") or 0)
    hit_dice = int(character_data.get("hitDice") or 0)
    con_score = int(character_data.get("conScore") or 0)

    con_mod = (con_score - 10) // 2

    max_hp = base_hp + (hit_dice // 2) * con_mod + temp_hp
    current_hp = max_hp - removed_hp
    hp_percent = current_hp / max_hp

    return hp_percent

# Takes the health data and sets the neopixels
def set_healthbar_neopixels(last_hp, hp):

    if hp == last_hp:
        return last_hp
    elif hp < last_hp:
        pulse_red()
    elif hp > last_hp:
        pulse_green()

    hp = max(0.0, min(1.0, hp))

    lit_pixels = int(num_pixels * hp)
    for i in range(num_pixels):
        if i < lit_pixels:
            pixels[i] = (0, 255, 0)
        else:
            pixels[i] = (255, 0, 0)
    pixels.show()

    return hp

def pulse_red(speed=0):
    for r in range(256):
        pixels.fill((r, 0, 0))
        pixels.show()
        time.sleep(speed)
    for r in range(255, -1, -1):
        pixels.fill((r, 0, 0))
        pixels.show()
        time.sleep(speed)

def pulse_green(speed=0):
    for g in range(256):
        pixels.fill((0, g, 0))
        pixels.show()
        time.sleep(speed)
    for g in range(255, -1, -1):
        pixels.fill((0, g, 0))
        pixels.show()
        time.sleep(speed)

def pulse_blue(speed=0):
    for b in range(256):
        pixels.fill((0, 0, b))
        pixels.show()
        time.sleep(speed)
    for b in range(255, -1, -1):
        pixels.fill((0, 0, b))
        pixels.show()
        time.sleep(speed)

def check_dead(hp):
    if hp < 0.0001:
        print("I get knocked down, but I get up again.")
        pulse_red(0.005)


def main():
    loop_exceptions = 0
    pulse_red()
    connect_wifi()
    pulse_blue()

    pool = socketpool.SocketPool(wifi.radio)
    ssl_context = ssl.create_default_context()
    session = adafruit_requests.Session(pool, ssl_context)

    last_hp = 0
    start = None


    while True:
        ws = None
        try:
            if start is None or (time.monotonic() - start) > refresh_at:
                token, ttl = get_token(session)
                gc.collect()
                print("token ok, ttl:", ttl)

            # Initial HP fetch
            try:
                print("Starting character fetch.")
                cdata = get_character(session, token)
                gc.collect()
                hp = calculate_hp(cdata)
                print("hp-init:", hp)
                last_hp = set_healthbar_neopixels(last_hp, hp)
                time.sleep(1)
            except Exception as e:
                print("hp-init-err:", e)
                start = None
                break

            while True:
                try:
                    ws_url = build_ws_url(token)
                    print("WS connecting...")
                    gc.collect()
                    print("mem_free pre-ws:", gc.mem_free())
                    ws = cpwebsockets.client.connect(ws_url, wifi.radio)
                    print("WS connected")

                    start = time.monotonic()
                    refresh_at = max(30, ttl - 30)

                    while True:
                        # refresh token/connection before expiry
                        if (time.monotonic() - start) > refresh_at:
                            print("token near expiry, reconnecting")
                            break

                        try:
                            msg = ws.recv()
                        except OSError as e:
                            if e.errno == errno.ETIMEDOUT:
                                print(e)
                                check_dead(hp)
                                continue
                            else:
                                print("ws recv err:", e)
                                break

                        if not msg:
                            continue

                        try:
                            evt = json.loads(msg)
                        except Exception:
                            # ignore non-JSON frames
                            continue

                        # Print raw event types for debugging
                        print("evt:", evt.get("eventType"))

                        if should_refresh_character(evt):
                            ws.close()
                            del ws
                            ws = None
                            gc.collect()
                            print("Character refresh, WS closed.")
                            break

                    break

                except OSError as e:
                    del ws
                    ws = None
                    del token
                    del start
                    start = None
                    gc.collect()
                    print(e)
                    time.sleep(10)
                    break

        except Exception as e:
            print("loop err:", repr(e))
            traceback.print_exception(type(e), e, e.__traceback__)
            time.sleep(3)
            loop_exceptions += 1
            if loop_exceptions > 3:
                wifi.radio.enabled = False
                wifi.radio.enabled = True
                gc.collect()
                main()
        finally:
            try:
                if ws is not None:
                    ws.close()
            except Exception:
                pass


main()
