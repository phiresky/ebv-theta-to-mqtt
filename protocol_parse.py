from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import struct
import crc
import json
import sys
from datetime import datetime, timezone
import zoneinfo
import strictyaml


def read_raw(p: Path):
    content = p.read_text()

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
# Siehe auch https://reveng.sourceforge.io/readme.htm
# reveng -a 8 -w 16 -s $(cat hexmessages)
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


def read_multiple_from_logs():
    full_data = b""
    for input_file in sys.argv[1:]:
        input_file = Path(input_file)
        print(input_file)
        if input_file.suffix == ".jsonl":
            yield from read_jsonl(input_file)
        else:
            timestamp = datetime.fromtimestamp(
                input_file.stat().st_mtime, tz=timezone.utc
            )
            yield timestamp, read_raw(input_file)


def stream_messages_from_logs():
    buffer = b""
    for timestamp, chunk in read_multiple_from_logs():
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
    for timestamp, message in stream_messages_from_logs():
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
