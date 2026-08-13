from pure_trace.serial_port import find_port


class _Port:
    """Sostituto di serial.tools.list_ports.ListPortInfo."""

    def __init__(self, device, vid=None):
        self.device = device
        self.vid = vid


def test_preferred_port_wins_when_present():
    ports = [_Port("/dev/ttyUSB0", vid=0x1A86), _Port("/dev/ttyACM0")]
    assert find_port(preferred="/dev/ttyACM0", ports=ports) == "/dev/ttyACM0"


def test_stale_preferred_port_is_ignored():
    """Una porta configurata ma assente non deve impedire l'avvio: era il caso
    di SERIAL_PORT='COM4' su Raspberry Pi."""
    ports = [_Port("/dev/ttyUSB0", vid=0x1A86)]
    assert find_port(preferred="COM4", ports=ports) == "/dev/ttyUSB0"


def test_detects_ch340_by_vendor_id():
    ports = [_Port("/dev/ttyS0"), _Port("/dev/ttyUSB0", vid=0x1A86)]
    assert find_port(ports=ports) == "/dev/ttyUSB0"


def test_detects_official_arduino_by_vendor_id():
    ports = [_Port("/dev/ttyACM0", vid=0x2341)]
    assert find_port(ports=ports) == "/dev/ttyACM0"


def test_falls_back_to_device_name_hint():
    ports = [_Port("/dev/ttyS0"), _Port("/dev/ttyACM0", vid=0x9999)]
    assert find_port(ports=ports) == "/dev/ttyACM0"


def test_returns_none_when_nothing_matches():
    assert find_port(ports=[_Port("/dev/ttyS0")]) is None
    assert find_port(ports=[]) is None
