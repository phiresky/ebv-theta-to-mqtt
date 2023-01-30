import asyncio_mqtt as aiomqtt
import paho.mqtt as mqtt
import asyncio
import json

async def main():
    async with aiomqtt.Client(
        hostname="homeautopi.fritz.box",
        port=1883,
        username="device",
        password="lxpjqubkxxwmjqzs",
    ) as client:
        await client.publish(
            "homeassistant/sensor/theta_mqtt_adapter_/config",
            json.dumps(
                {
                    "name": "Temp Foo",
                    "object_id": "theta_temp_xxx_foo",
                    "device_class": "temperature",
                    "state_topic": "homeassistant/sensor/theta_temp_xxx_foo/state",
                    "unit_of_measurement": "°C",
                    "unique_id": "theta_temp_xxx_foo",
                }
            ),
            retain=True,
        )


def on_log(client, userdata, level, buf):
    print(userdata, level, buf)


asyncio.run(main())
