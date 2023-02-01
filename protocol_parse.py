from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import struct
import crc
import json
import sys
from datetime import datetime
import zoneinfo
import strictyaml


def read_raw(p: Path):
    content = Path("b").read_text()

    content = bytes.fromhex(content)
    return content


def read_jsonl(p: Path):
    content = Path(p).read_text()
    b = b""
    for line in content.splitlines():
        content = json.loads(line)
        yield datetime.fromisoformat(content["time"]), bytes.fromhex(content["data"])


# CRC-16 CCITT KERMIT
# same as https://github.com/bogeyman/gamma/wiki/Protokoll
# Zum ausprobieren: https://www.lammertbies.nl/comm/info/crc-calculation.html oder https://www.tahapaksu.com/crc/ öffnen und HEX als Modus auswählen, "10200905004113141780150108" als Nachricht eintragen und die Checksumme berechnen lassen. Der Wert bei der Kermit Variante sollte "0x5F2F" annehmen...
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

message_prefix = b"\x21\x0a\x0a"


def read_multiple():
    full_data = b""
    for input_file in sys.argv[1:]:
        input_file = Path(input_file)
        print(input_file)
        if input_file.suffix == ".jsonl":
            yield from read_jsonl(input_file)
        else:
            yield from read_raw(input_file)


def stream_messages():
    buffer = b""
    for timestamp, chunk in read_multiple():
        buffer += chunk
        while True:
            try:
                start_msg_idx = buffer.index(message_prefix)
                end_msg_idx = buffer.index(message_prefix, start_msg_idx + 1)
                yield timestamp, buffer[start_msg_idx:end_msg_idx]
                buffer = buffer[end_msg_idx:]
            except ValueError as e:
                # could not find message
                break


last_msg = None


def parse_message(
    timestamp: datetime, message: bytes, plot_data: dict[str, list[dict]] | None
):
    global last_msg
    if message == last_msg:
        return
    last_msg = message
    prefix = message[0:3]
    assert prefix == message_prefix
    message = message[3:]
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
        seconds, minutes, hours, day, month, year, decade = struct.unpack(
            "BBBBBBB", rest_message
        )
        # seems to only be minute accuracy
        year = year + decade * 100 + 1900  # i guess maybe?
        fulltime = datetime(
            year,
            month,
            day,
            hours,
            minutes,
            seconds,
            tzinfo=zoneinfo.ZoneInfo("Europe/Berlin"),
        )
        print(f"time: {fulltime}")
    if m_ty == 0xFF and idk == 1:
        parsenum = rest_message[7] + rest_message[8] * 256
        print(f"m_ty=ff parse attempt: {parsenum}")
        plot_data["interesting_0xff+7"].append(
            dict(timestamp=timestamp, value=parsenum)
        )
    if m_ty == 0xB1 and idk == 1:
        _, _, _, countdown, one, zero = struct.unpack("<IIHHBB", rest_message)
        print(f"m_ty=b1 parse attempt countdown: {countdown} s {one=} {zero=}")
    if m_ty == 0xC2 and idk == 1:
        data = struct.unpack("<BBBBBBBBBBBBBBBBBBBBBBBBI", rest_message)
        on_off = data[10]
        min_burn_time_countdown = data[-9]
        temp = data[-3]
        print(
            f"m_ty=c2 parse attempt countdown: {on_off=} {min_burn_time_countdown=} {temp=}"
        )
        plot_data["burner_on"].append(dict(timestamp=timestamp, value=on_off))
        plot_data["burn_time_countdown"].append(
            dict(timestamp=timestamp, value=min_burn_time_countdown)
        )
        plot_data["interesting_0xc2+xx"].append(dict(timestamp=timestamp, value=temp))
        pass
    if m_ty in [0x1C, 0x1D, 0x1E, 0x1F]:
        vals = struct.unpack("<HHHH", rest_message[0:8])
        for i, val in enumerate(vals):
            plot_data[f"interesting_{m_ty:x}+{i*2}"].append(
                dict(timestamp=timestamp, value=val)
            )
    if m_ty == 0xB8 and idk == 1:
        # something with the water heating pump
        interesting_bytes = [3, 4, 5, 9, 13, 14, 15]
        for b in interesting_bytes:
            (int_val,) = struct.unpack("B", rest_message[b : b + 1])
            plot_data[f"interesting_0xb8+{b}"].append(
                dict(timestamp=timestamp, value=int_val)
            )
    if m_ty == 0xA4:
        int_1 = rest_message[4]
        int_2 = rest_message[-4]
        (int_3,) = struct.unpack("<H", rest_message[-3:-1])
        for val, ofs in zip([int_1, int_2, int_3], [4, "-4", "-3"]):
            plot_data[f"interesting_0xa4+{ofs}"].append(
                dict(timestamp=timestamp, value=val)
            )
    if m_ty == 0xA9 and idk == 1:
        # sensors?
        interesting_bytes = struct.unpack("<hHHHHHHHH", rest_message[0:18])
        for b, int_val in enumerate(interesting_bytes):
            plot_data[f"interesting_0xa9+{b*2}"].append(
                dict(timestamp=timestamp, value=int_val)
            )
    if m_ty == 0xAF and idk == 1:
        (interesting_1,) = struct.unpack("B", rest_message[4:5])
        (interesting_2,) = struct.unpack("<H", rest_message[10:12])
        plot_data["interesting_0xaf+4"].append(
            dict(timestamp=timestamp, value=interesting_1)
        )
        plot_data["interesting_0xaf+10"].append(
            dict(timestamp=timestamp, value=interesting_2)
        )
    if m_ty == 0xBD and idk == 1:
        (interesting,) = struct.unpack("<H", rest_message[22:24])
        (interesting_2,) = struct.unpack("<H", rest_message[28:30])
        plot_data["interesting_0xbd+22"].append(
            dict(timestamp=timestamp, value=interesting)
        )
        plot_data["interesting_0xbd+28"].append(
            dict(timestamp=timestamp, value=interesting_2)
        )
    rest_message_bytes = [i for i in rest_message]
    # print(f"{m_ty=:x} {idk=} {m_len=} {rest_message_bytes=}")
    print(f"{m_ty=:x} {idk=} {m_len=} {rest_message.hex(' ')=}")
    if len(message) != m_len + 1 + 3 + 2:
        print(
            f"{message.hex()} does not have expected format, read len as {m_len} but len is {len(message) - 1 - 3 - 2}"
        )


def get_interesting_values() -> list[dict]:
    from strictyaml import Seq, HexInt, Int, Str, Optional, Map, Bool, Float

    interesting_values = strictyaml.dirty_load(
        Path("interesting_values.yaml").read_text(),
        schema=Seq(
            Map(
                {
                    "message_type": Seq(HexInt() | Int()),
                    "byte_offset": Int(),
                    "format": Str(),
                    Optional("mqtt_component"): Str(),
                    Optional("name"): Str(),
                    Optional("hidden"): Bool(),
                    Optional("unit"): Str(),
                    Optional("scale_factor"): Float(),
                    Optional("state_class"): Str(),
                }
            )
        ),
        allow_flow_style=True,
    ).data
    for v in interesting_values:
        if "unique_id" not in v:
            m_ty_1, m_ty_2 = v["message_type"]
            byte_offset = v["byte_offset"]
            format = v["format"]
            v[
                "unique_id"
            ] = f"m_ty={m_ty_1:02x}{m_ty_2:02x},byte_ofs={byte_offset},format={format}"
    return interesting_values


def get_interesting_map():
    interesting_values = get_interesting_values()
    interesting_map = {}
    for e in interesting_values:
        k = tuple(e["message_type"])
        if k not in interesting_map:
            interesting_map[k] = []
        interesting_map[k].append(e)
    return interesting_map


@dataclass
class ReadValue:
    info: dict
    unique_id: str
    readable_name: str
    value_raw: int


def parse_message_v2(
    interesting_map: dict[tuple[int, int], dict], message: bytes
) -> list[ReadValue]:
    global last_msg
    if message == last_msg:
        return []
    last_msg = message
    prefix = message[0:3]
    assert prefix == message_prefix
    message = message[3:]
    m_ty_1 = message[0]
    m_ty_2: int = message[1]
    idk_2 = message[2]
    assert idk_2 == 0
    m_len = message[3]
    (checksum,) = struct.unpack("<H", message[-2:])
    rest_message = message[4:-2]
    fullsumsource = prefix + message[:-2]
    calcsum = crccalc.checksum(fullsumsource)
    if calcsum != checksum:
        print(f"checksum does not match: {calcsum=} {checksum=} {message.hex()=}")
        return []
    if len(message) != m_len + 1 + 3 + 2:
        print(
            f"{message.hex()} does not have expected format, read len as {m_len} but len is {len(message) - 1 - 3 - 2}"
        )
        return []
    print(f"{m_ty_1:02x}{m_ty_2:02x} hex={rest_message.hex(' ')}")

    format_map = {
        "u8": "B",
        "i8": "b",
        "u16le": "<H",
        "i16le": "<h",
        "u32le": "<I",
    }
    read_values = []
    for e in interesting_map.get((m_ty_1, m_ty_2), []):
        byte_offset = e["byte_offset"]
        format = e["format"]
        name = e.get("name", None)
        unique_id = e["unique_id"]
        (value,) = struct.unpack_from(format_map[format], rest_message, byte_offset)

        read_values.append(
            ReadValue(info=e, unique_id=unique_id, readable_name=name, value_raw=value)
        )
    return read_values


def parse_and_plot():
    interesting_map = get_interesting_map()
    plot_data = defaultdict(list)
    for timestamp, message in stream_messages():
        try:
            values = parse_message_v2(interesting_map, message)
            for value in values:
                if not value.info.get("hidden", False) and value.value_raw < 200000:
                    # print(f"{value.readable_name or value.unique_id}: {value.value_raw}")
                    plot_data[value.readable_name or value.unique_id].append(
                        dict(timestamp=timestamp, value=value.value_raw)
                    )
        except Exception as e:
            print(f"could not parse {message}: {e}")

    import plotly.express as px
    import pandas

    all_plotdata = None
    for title, data in plot_data.items():
        df = (
            pandas.DataFrame(data)
            .set_index("timestamp")
            .rename(columns={"value": title})
        )
        if all_plotdata is None:
            all_plotdata = df
        else:
            all_plotdata = pandas.merge(all_plotdata, df, how="outer", on="timestamp")
    print(all_plotdata)
    fig = px.scatter(all_plotdata)
    fig.show()


if __name__ == "__main__":
    parse_and_plot()
