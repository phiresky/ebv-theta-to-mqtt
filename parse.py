from collections import defaultdict
from pathlib import Path
import struct
import crc
import json
import sys
from datetime import datetime
import zoneinfo

def read_raw(p: Path):
    content = Path("b").read_text()

    content = bytes.fromhex(content)
    return content


def read_jsonl(p: Path):
    content = Path(p).read_text()
    b = b""
    for line in content.splitlines():
        content = json.loads(line)
        b += bytes.fromhex(content["data"])
    return b


crccalc = crc.Calculator(
    crc.Configuration(
        width=16,
        polynomial=0x1021,
        init_value=0x0000,
        final_xor_value=0x0000,
        reverse_input=True,
        reverse_output=True,
    )
)

prefix = b"\x21\x0a\x0a"

full_data = b""
for input_file in sys.argv[1:]:
    input_file = Path(input_file)
    print(input_file)
    if input_file.suffix == ".jsonl":
        full_data += read_jsonl(input_file)
    else:
        full_data += read_raw(input_file)

messages = full_data.split(prefix)


last_msg = None

plot_data = defaultdict(list)
def parse_message(message):
    global last_msg
    if message == last_msg:
        return
    last_msg = message
    m_ty = message[0]
    idk = message[1]
    idk_2 = message[2]
    assert idk_2 == 0
    m_len = message[3]
    (checksum,) = struct.unpack("<H", message[-2:])
    rest_message = message[4:-2]
    fullsumsource = prefix + message[:-2]
    calcsum = crccalc.checksum(fullsumsource)
    if calcsum != checksum:
        print(f"checksum does not match: {calcsum=} {checksum=} {message.hex()=}")

    if m_ty == 10:
        (val,) = struct.unpack("<I", rest_message)
        print(f"Betriebsstunden: {val/3600:.3f} h")
    if m_ty == 11:
        (val,) = struct.unpack("<I", rest_message)
        print(f"Starts: {val}")
    if m_ty == 18 and idk == 5:
        temp_1, temp_2, temp_3, temp_4 = struct.unpack("BBBB", rest_message)
        print(f"vllt temps: {temp_1/2-52}°C, {temp_2/2-52}°C {temp_3/2-52}°C")
        pass
    if m_ty == 70 and idk == 0:
        seconds, minutes, hours, day, month, year, decade = struct.unpack("BBBBBBB", rest_message)
        year = year + decade * 100 + 1900 # i guess maybe?
        fulltime = datetime(year, month, day, hours, minutes, seconds, tzinfo=zoneinfo.ZoneInfo("Europe/Berlin"))
        print(f"time: {fulltime}")
    if m_ty == 255 and idk == 1:
        parsenum = rest_message[7] + rest_message[8] * 256
        print(f"m_ty=ff parse attempt: {parsenum}")
    if m_ty == 0xb1 and idk == 1:
        _, _, _, countdown, one, zero = struct.unpack("<IIHHBB", rest_message)
        print(f"m_ty=b1 parse attempt countdown: {countdown} s {one=} {zero=}")
    if m_ty == 0xc2 and idk==1:
        data = struct.unpack("<BBBBBBBBBBBBBBBBBBBBBBBBI", rest_message)
        on_off = data[10]
        min_burn_time_countdown = data[-8]
        temp = data[-3]
        print(f"m_ty=c2 parse attempt countdown: {on_off=} {min_burn_time_countdown=} {temp=} {temp/2} {temp/2-52}")
        pass
    if m_ty == 0xbd and idk == 1:
        interesting, = struct.unpack("<H", rest_message[22:24])
        plot_data["interesting_0xbd+22"].append(interesting)

    rest_message_bytes = [i for i in rest_message]
    # print(f"{m_ty=:x} {idk=} {m_len=} {rest_message_bytes=}")
    print(f"{m_ty=:x} {idk=} {m_len=} {rest_message.hex(' ')=}")
    if len(message) != m_len + 1 + 3 + 2:
        print(
            f"{message.hex()} does not have expected format, read len as {m_len} but len is {len(message) - 1 - 3 - 2}"
        )


for message in messages:
    if len(message) == 0:
        continue
    try:
        parse_message(message)
    except Exception as e:
        print(f"could not parse {message}: {e}")

import plotly.express as px
for title, data in plot_data.items():
    fig = px.scatter(data, title=title)
    fig.show()
