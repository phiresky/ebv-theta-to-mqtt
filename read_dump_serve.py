from serial_asyncio import open_serial_connection
import datetime
import json
from pathlib import Path
import protocol_parse

nowstamp = datetime.now().astimezone().isoformat(timespec="seconds")

async def yield_data_from_com():
    with Path(f"dump-{nowstamp}.jsonl").open("w", encoding="utf8") as f:
        com_reader, _ = await open_serial_connection(url="/dev/ttyUSB0", baudrate=9600, timeout=1)
        while True:
            data = await com_reader.read(50)
            dump_line = {"time": datetime.now().astimezone().isoformat(), "data": data.hex()}
            f.write(
                json.dumps(
                    dump_line
                ) + "\n"
            )
            yield data

async def split_messages(read_stream):
    buffer = b""
    async for timestamp, chunk in read_stream:
        buffer += chunk
        while True:
            try:
                start_msg_idx = buffer.index(protocol_parse.message_prefix)
                end_msg_idx = buffer.index(protocol_parse.message_prefix, start_msg_idx + 1)
                yield timestamp, buffer[start_msg_idx:end_msg_idx]
                buffer = buffer[end_msg_idx:]
            except ValueError as e:
                # could not find message
                break

async def main():
    data_chunks = yield_data_from_com()
    messages = split_messages(data_chunks)