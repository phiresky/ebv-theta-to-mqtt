import asyncio
from io import TextIOWrapper
import asyncio_mqtt
from serial_asyncio import open_serial_connection
import datetime
import json
from pathlib import Path
import protocol_parse


class Config:
    serial_port: str = "/dev/ttyUSB0"
    mqtt_conn: dict = dict(
        hostname="homeautopi.fritz.box",
        port=1883,
        username="device",
        password="lxpjqubkxxwmjqzs",
    )
    mqtt_topic_root: str = "homeassistant/sensor/ebv_theta_mqtt_adapter"


log_file = None
log_file_stamp: TextIOWrapper | None = None


def dump_log_line(obj: dict):
    global log_file, log_file_stamp
    nowstamp = datetime.now().astimezone().isoformat(timespec="hours")
    if log_file_stamp != nowstamp:
        log_file_stamp = nowstamp
        if log_file is not None:
            log_file.close()
        Path("dumps").mkdir(exist_ok=True)
        log_file = Path(f"dumps/{nowstamp}.jsonl").open("a", encoding="utf8")
    log_file.write(json.dumps(obj) + "\n")


async def yield_data_from_com(config: Config):
    com_reader, _ = await open_serial_connection(
        url=config.serial_port, baudrate=9600, timeout=1
    )
    while True:
        data = await com_reader.read(100)
        dump_log_line(
            {"time": datetime.now().astimezone().isoformat(), "data": data.hex()}
        )
        yield data


async def split_messages(read_stream):
    buffer = b""
    async for timestamp, chunk in read_stream:
        buffer += chunk
        while True:
            # find messages in chunk
            try:
                start_msg_idx = buffer.index(protocol_parse.message_prefix)
                end_msg_idx = buffer.index(
                    protocol_parse.message_prefix, start_msg_idx + 1
                )
                yield timestamp, buffer[start_msg_idx:end_msg_idx]
                buffer = buffer[end_msg_idx:]
            except ValueError as e:
                # could not find complete message
                break


async def loop_send_current_value(
    config: Config, mqtt_client: asyncio_mqtt.Client, value: dict
):
    while True:
        await asyncio.sleep(1)
        await mqtt_client.publish(f"{config.mqtt_topic_root}/value", json.dumps(value))


async def loop_read_parse_values(config: Config, value: dict):
    interesting_map = protocol_parse.get_interesting_values()
    data_chunks = yield_data_from_com(config)
    messages = split_messages(data_chunks)
    async for message in messages:
        for update in protocol_parse.parse_message_v2(interesting_map, message):
            value[update.unique_id] = update.value_raw


async def main():
    config = Config()
    async with asyncio_mqtt.Client(**config.mqtt_conn) as mqtt_client:
        current_value = {}
        coroutine1 = loop_send_current_value(config, mqtt_client, current_value)

        coroutine2 = loop_read_parse_values(config, current_value)

        asyncio.gather(coroutine1, coroutine2)


asyncio.run(main())
