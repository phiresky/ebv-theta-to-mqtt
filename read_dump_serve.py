import asyncio
from io import TextIOWrapper
import re
import asyncio_mqtt
from serial_asyncio import open_serial_connection
from datetime import datetime
import json
from pathlib import Path
import protocol_parse
from tap import Tap


class Config(Tap):
    serial_port: str = "/dev/ttyUSB0"
    mqtt_hostname: str = "homeautopi.fritz.box"
    mqtt_port: int = 1883
    mqtt_username = "device"
    mqtt_password = "lxpjqubkxxwmjqzs"
    mqtt_topic_root: str = "homeassistant"
    mqtt_id_prefix: str = "ebv_theta_mqtt_adapter"
    send_interval_s: int = 30


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
        logpath = f"dumps/{nowstamp}.jsonl"
        print(f"opening new logpath {logpath}")
        log_file = Path(logpath).open("a", encoding="utf8")
    log_file.write(json.dumps(obj) + "\n")


async def yield_data_from_com(config: Config):
    com_reader, _ = await open_serial_connection(
        url=config.serial_port, baudrate=9600, timeout=1
    )
    while True:
        data = await com_reader.read(100)
        timestamp = datetime.now().astimezone()
        dump_log_line({"time": timestamp.isoformat(), "data": data.hex()})
        yield timestamp, data


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
        await asyncio.sleep(config.send_interval_s)
        await mqtt_client.publish(
            f"{config.mqtt_topic_root}/sensor/{config.mqtt_id_prefix}/state",
            json.dumps(value),
        )


async def loop_read_parse_values(config: Config, value: dict):
    interesting_map = protocol_parse.get_interesting_map()
    data_chunks = yield_data_from_com(config)
    messages = split_messages(data_chunks)
    async for _timestamp, message in messages:
        try:
            for update in protocol_parse.parse_message_v2(interesting_map, message):
                value[update.unique_id] = update.value_raw
        except Exception as e:
            print(f"could not parse {message.hex(' ')=}", e)


async def mqtt_announce_sensors(config: Config, mqtt_client: asyncio_mqtt.Client):
    interesting_values = protocol_parse.get_interesting_values()
    for value in interesting_values:
        if "name" not in value or value.get("hidden", False):
            continue
        unique_id = value["unique_id"]
        mqtt_id = re.sub("[^a-zA-Z0-9_-]", "_", f"{config.mqtt_id_prefix}_{unique_id}")
        unit = value.get("unit", None)
        mqtt_component = value.get("mqtt_component", "sensor")
        device_class = {"°C": "temperature", "s": "duration"}.get(unit, None)
        scale_factor = value.get("scale_factor", 1)
        mqtt_msg = {
            "name": f"Theta {value.get('name', unique_id)}",
            "object_id": mqtt_id,
            "device_class": device_class,
            "state_topic": f"{config.mqtt_topic_root}/sensor/{config.mqtt_id_prefix}/state",
            "unique_id": mqtt_id,
            "value_template": f"{{{{ value_json['{unique_id}'] / {scale_factor} }}}}",
        }
        if unit is not None:
            mqtt_msg["unit_of_measurement"] = unit
        if mqtt_component == "binary_sensor":
            mqtt_msg.update({"payload_on": "1.0", "payload_off": "0.0"})
        await mqtt_client.publish(
            f"{config.mqtt_topic_root}/{mqtt_component}/{mqtt_id}/config",
            json.dumps(mqtt_msg),
            retain=True,
        )


async def main():
    config = Config().parse_args()
    async with asyncio_mqtt.Client(
        hostname=config.mqtt_hostname,
        port=config.mqtt_port,
        username=config.mqtt_username,
        password=config.mqtt_password,
    ) as mqtt_client:
        await mqtt_announce_sensors(config, mqtt_client)
        current_value = {}
        coroutine1 = loop_send_current_value(config, mqtt_client, current_value)

        coroutine2 = loop_read_parse_values(config, current_value)

        await asyncio.gather(coroutine1, coroutine2)


asyncio.run(main())
