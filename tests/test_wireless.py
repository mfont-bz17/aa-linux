import unittest
from importlib import import_module


wireless = import_module("aa-linux.wireless")


class WirelessTests(unittest.TestCase):
    def test_rfcomm_frame_round_trip(self):
        frame = wireless.build_rfcomm_frame(7, b"payload")
        self.assertEqual(
            wireless.parse_rfcomm_frame(frame + b"extra"),
            (7, b"payload", b"extra"),
        )


    def test_rfcomm_channel_parser(self):
        sdp = """Service RecHandle: 0x10001
Service Class ID List:
  UUID 128: 4de17a00-52cb-11e6-bdf4-0800200c9a66
Protocol Descriptor List:
  \"RFCOMM\" (0x0003)
    Channel: 3
"""
        self.assertEqual(wireless.find_rfcomm_channel(sdp, "4de17a00"), 3)


if __name__ == "__main__":
    unittest.main()
