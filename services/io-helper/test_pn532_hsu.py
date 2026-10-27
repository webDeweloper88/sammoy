import os
import pty
import threading
import time
import unittest
from unittest.mock import patch
from pn532_hsu import ACK, NAK, WAKE, LinuxHsuPn532, encode, extract, target_info


def response(data):
    return b'\0\0\xff'+bytes([len(data),-len(data)&255])+data+bytes([-sum(data)&255,0])


class HsuTests(unittest.TestCase):
    def test_frame_checksum_and_partial_response(self):
        self.assertEqual(encode(b'\x02'),bytes.fromhex('0000ff02fed4022a00'))
        buf=bytearray(ACK[:3]); self.assertIsNone(extract(buf))
        buf.extend(ACK[3:]+response(bytes.fromhex('d50332010607')))
        self.assertEqual(extract(buf),('ack',b''))
        self.assertEqual(extract(buf),('data',bytes.fromhex('d50332010607')))
        self.assertEqual(buf,bytearray())

    def test_invalid_length_checksum_postamble_and_nak(self):
        self.assertEqual(extract(bytearray(NAK)),('nak',b''))
        for value in ('0000ff0200d5032800','0000ff02fed5030000','0000ff02fed5032801'):
            with self.assertRaises(RuntimeError):extract(bytearray.fromhex(value))
        with self.assertRaises(RuntimeError):extract(bytearray(b'x'*300))

    def test_metadata_from_single_target_response(self):
        self.assertEqual(target_info(bytes.fromhex('01010004200401020304')),
                         {'uid':b'\x01\x02\x03\x04','sak':32,'atqa':'0004'})
        self.assertIsNone(target_info(b'\0'))
        for raw in (b'',b'\x02',bytes.fromhex('0101000408070102')):
            with self.assertRaises(RuntimeError):target_info(raw)

    def serial_case(self, emulator):
        master, slave=pty.openpty()
        self.addCleanup(os.close,master);self.addCleanup(os.close,slave)
        reader=LinuxHsuPn532(os.ttyname(slave));self.addCleanup(reader.close)
        errors=[]
        def work():
            try:emulator(master)
            except BaseException as e:errors.append(e)
        t=threading.Thread(target=work,daemon=True);t.start()
        return reader,t,errors

    def test_pty_wake_fragmentation_and_firmware(self):
        seen=[]
        def emulator(fd):
            data=b''
            while len(data)<len(WAKE)+9:data+=os.read(fd,256)
            seen.append(data)
            reply=ACK+response(bytes.fromhex('d50332010607'))
            for value in reply:
                os.write(fd,bytes([value]));time.sleep(.001)
        reader,t,errors=self.serial_case(emulator)
        self.assertEqual(reader.firmware_version,(50,1,6,7))
        t.join(1);self.assertFalse(errors)
        self.assertEqual(seen,[WAKE+encode(b'\x02')])
        reader.close();reader.close()
        with self.assertRaises(OSError):reader.firmware_version

    def test_timeout_is_bounded_and_cancels_poll(self):
        reader,t,errors=self.serial_case(lambda fd:None)
        start=time.monotonic()
        with self.assertRaises(TimeoutError):reader._command(b'\x02',timeout=.03)
        self.assertLess(time.monotonic()-start,.5)

    def test_wrong_command_and_nak_rejected(self):
        for reply in (NAK,ACK+response(bytes.fromhex('d515'))):
            def emulator(fd):os.read(fd,256);os.write(fd,reply)
            reader,t,errors=self.serial_case(emulator)
            with self.assertRaises(RuntimeError):reader.firmware_version
            t.join(1);self.assertFalse(errors)
            reader.close()

    def test_fd_closed_when_constructor_fails(self):
        master,slave=pty.openpty()
        try:
            realclose=os.close
            with patch('pn532_hsu.termios.tcgetattr',side_effect=OSError('bad')),patch('pn532_hsu.os.close',wraps=realclose) as close:
                with self.assertRaises(OSError):LinuxHsuPn532(os.ttyname(slave))
                close.assert_called_once()
        finally:os.close(master);os.close(slave)
