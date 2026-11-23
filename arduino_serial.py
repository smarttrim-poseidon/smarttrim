
import math
import serial
from serial.tools import list_ports


def available_ports():
    """Return available serial ports."""
    return [
        (port.device, port.description)
        for port in list_ports.comports()
    ]


def parse_sensor_line(line):
    """Parse Arduino CSV: timestamp_ms,roll_deg,pitch_deg."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")

    line = line.strip()

    if not line or line.startswith("#"):
        return None

    parts = line.split(",")

    if len(parts) != 3:
        return None

    try:
        timestamp = int(parts[0].strip())
        roll = float(parts[1].strip())
        pitch = float(parts[2].strip())
    except (ValueError, TypeError):
        return None

    if timestamp < 0:
        return None

    if not all(math.isfinite(v) for v in (roll, pitch)):
        return None

    return {
        "timestamp_ms": timestamp,
        "roll_deg": roll,
        "pitch_deg": pitch,
        "source": "arduino_mpu6050",
    }


def connect_arduino(port, baudrate=115200):
    """Open a serial connection with a short timeout."""
    return serial.Serial(
        port=port,
        baudrate=baudrate,
        timeout=0.1,
    )


def parse_status_line(line):
    """Return the text of a '#' status line from the sketch, else None."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    line = line.strip()
    if not line.startswith("#"):
        return None
    return line[1:].strip() or None


def read_line(connection):
    """Read one serial line -> (measurement or None, status text or None).

    readline() returns a partial line when its timeout expires (for example
    b"5160,1.250,-2" while "-2.500" is still in transit). Such a fragment can
    still look like valid CSV, so only newline-terminated lines are accepted.
    """
    raw = connection.readline()
    if not raw or not raw.endswith(b"\n"):
        return None, None
    return parse_sensor_line(raw), parse_status_line(raw)


def read_measurement(connection):
    """Read and parse one complete serial line; partial lines return None."""
    return read_line(connection)[0]


def disconnect_arduino(connection):
    """Close an existing serial connection."""
    if connection is not None and connection.is_open:
        connection.close()

def is_arduino_connected(connection):
    """Check whether a serial connection is open."""
    if connection is None:
        return False

    try:
        return connection.is_open
    except (serial.SerialException, OSError):
        return False


def safe_disconnect(connection):
    """Close the serial port without crashing on disconnection."""
    if connection is None:
        return

    try:
        if connection.is_open:
            connection.close()
    except (serial.SerialException, OSError):
        pass
