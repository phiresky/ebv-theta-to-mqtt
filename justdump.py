import serial
from pathlib import Path
from datetime import datetime
import json

nowstamp = datetime.now().astimezone().isoformat(timespec="seconds")
with (
    Path(f"dump-{nowstamp}.jsonl").open("w", encoding="utf8") as f,
    serial.Serial("/dev/ttyUSB0", baudrate=9600, timeout=1) as s,
):
    while True:
        data = s.read(100)
        line = {"time": datetime.now().astimezone().isoformat(), "data": data.hex()}
        f.write(
            json.dumps(
                line
            )
        )
        f.write("\n")
        print(line)
