"""Hardware-free tests for the Arduino serial contract (timestamp_ms,roll_deg,pitch_deg)."""
from arduino_serial import parse_sensor_line, parse_status_line, read_line, read_measurement


class FakeConnection:
    """Mimics serial.Serial.readline(): returns queued bytes, b'' when empty."""

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def readline(self):
        return self.chunks.pop(0) if self.chunks else b""


def test_data_line_parses_in_degrees_and_ms():
    row = parse_sensor_line(b"5160,1.250,-2.500\r\n")
    assert row == {"timestamp_ms": 5160, "roll_deg": 1.25, "pitch_deg": -2.5,
                   "source": "arduino_mpu6050"}


def test_header_and_status_lines_from_original_sketch_are_not_data():
    for line in (b"timestamp_ms,roll_deg,pitch_deg\r\n",
                 b"# CALIBRATING: keep vessel stationary and approximately level for 3 seconds\r\n",
                 b"# CALIBRATION_OK\r\n",
                 b"# WARN: sample gap; resetting integration interval\r\n",
                 b"# ERROR: I2C read failed\r\n"):
        assert parse_sensor_line(line) is None


def test_status_line_text():
    assert parse_status_line(b"# WARN: zero captured while tilted\r\n") == \
        "WARN: zero captured while tilted"
    assert parse_status_line(b"5160,1.250,-2.500\r\n") is None
    assert parse_status_line(b"#\r\n") is None


def test_timed_out_partial_line_is_rejected():
    # Before the fix this fragment was accepted with pitch_deg == -2.0.
    connection = FakeConnection([b"5160,1.250,-2", b"500\r\n", b"5180,1.300,-2.400\r\n"])
    assert read_measurement(connection) is None
    assert read_measurement(connection) is None
    assert read_measurement(connection)["pitch_deg"] == -2.4


def test_read_line_returns_status_and_data_separately():
    connection = FakeConnection([b"# CALIBRATING: keep vessel stationary\r\n",
                                 b"5160,1.250,-2.500\n", b""])
    assert read_line(connection) == (None, "CALIBRATING: keep vessel stationary")
    measurement, status = read_line(connection)
    assert status is None and measurement["roll_deg"] == 1.25
    assert read_line(connection) == (None, None)
