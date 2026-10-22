import os
from queue import Queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from bill_process_reader import ProcessLevelReader, FRAME, gpio_fd, sample
from bill_filter import BillFilter


class ProcessReaderTests(unittest.TestCase):
    def test_reconfigure_keeps_gpio_handle_and_replaces_sampler_state(self):
        reader=self.reader();line=reader.line
        reader.close=Mock();reader.start=Mock();start=reader.start
        reader.reconfigure(False,False,10,25)
        self.assertIs(reader.line,line);self.assertFalse(reader.active_low)
        self.assertEqual(reader.gap_limit_ms,25);self.assertEqual(reader.last_at,10)
        self.assertFalse(reader.stop.is_set());start.assert_called_once()
    def test_normal_priority_applies_only_when_explicitly_requested(self):
        with patch.dict(os.environ,{'IO_BILL_SAMPLER_NICE':'-10'}),patch('bill_process_reader.os.setpriority',side_effect=PermissionError) as scheduler:
            with self.assertRaises(PermissionError):sample(123,456,True,False,5)
            scheduler.assert_called_once_with(os.PRIO_PROCESS,0,-10)

    def reader(self):return ProcessLevelReader(Mock(),True,False,0,5)
    def packet(self,at,active,changed=True,uncertain=False,samples=1):
        return FRAME.pack(1,at,2,2,samples,0,int(active)|(int(changed)<<1)|(int(uncertain)<<2))

    def test_delayed_consumer_keeps_200_actual_pulses(self):
        r=self.reader();f=BillFilter({},False,0);f.poll(.5)
        for n in range(200):
            r._packet(self.packet(1+n*.15,True,samples=n*2+1))
            r._packet(self.packet(1.05+n*.15,False,samples=n*2+2))
        self.assertEqual(r.snapshot()['queued_transitions'],400)
        while r.pending():
            e=r.read();f.edge(e.active,e.at)
        self.assertEqual(f.accepted,200)

    def test_uncertain_gap_is_not_silently_reconstructed(self):
        r=self.reader();r._packet(self.packet(1,False,False,True))
        e=r.read();self.assertTrue(e.uncertain);self.assertFalse(e.changed)
        self.assertFalse(r.pending())

    def test_pipe_fragmentation_and_eof_latch_failure(self):
        r=self.reader();read_fd,write_fd=os.pipe();r._pipe=read_fd
        packet=self.packet(1,True)
        thread=threading.Thread(target=r._receive);thread.start()
        os.write(write_fd,packet[:5]);os.write(write_fd,packet[5:]);os.close(write_fd)
        thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(r.error,'reader_failed')
        self.assertTrue(r.read().active);self.assertIsNone(r._pipe)

    def test_real_subprocess_preserves_stream_while_parent_waits(self):
        r=self.reader();read_fd,write_fd=os.pipe();r._pipe=read_fd
        code="import os,sys,struct;f=struct.Struct('!BdddQQB');fd=int(sys.argv[1]);[(os.write(fd,f.pack(1,1+n*.15,2.,2.,n*2+1,0,3)),os.write(fd,f.pack(1,1.05+n*.15,2.,2.,n*2+2,0,2))) for n in range(200)]"
        child=subprocess.Popen([sys.executable,'-c',code,str(write_fd)],pass_fds=(write_fd,))
        os.close(write_fd)
        # The sampler can fill the pipe while the application consumes nothing.
        time.sleep(.03)
        thread=threading.Thread(target=r._receive);thread.start()
        child.wait(timeout=3);thread.join(3)
        self.assertEqual(r.queue.qsize(),400)
        self.assertEqual(r.error,'reader_failed') # Unexpected sampler exit must fail closed.

    def test_overflow_and_invalid_observations_fail_closed(self):
        r=self.reader();r.queue=Queue(maxsize=1)
        r._packet(self.packet(1,True));r._packet(self.packet(1.05,False,samples=2))
        self.assertEqual(r.error,'reader_overflow')
        for packet in (FRAME.pack(3,1,2,2,1,0,0),FRAME.pack(1,float('nan'),2,2,1,0,0),FRAME.pack(1,1,2,2,1,0,8)):
            with self.assertRaises(ValueError):self.reader()._packet(packet)

    def test_gpio_fd_uses_existing_handle_and_never_requests_line(self):
        read_fd,write_fd=os.pipe()
        try:
            line=Mock();line._throw_if_null_and_get_m_line.return_value=SimpleNamespace(fd_handle=SimpleNamespace(fd=read_fd))
            self.assertEqual(gpio_fd(line),read_fd);line.request.assert_not_called()
        finally:os.close(read_fd);os.close(write_fd)

    def test_sampler_only_reads_gpio_and_reports_observed_changes(self):
        sent=[]
        def ioctl(fd,request,buffer,mutate):buffer[0]=next(values)
        values=iter([1,0,1])
        def sleep(_):
            if len(sent)==3:raise InterruptedError()
        with patch('bill_process_reader.fcntl.ioctl',side_effect=ioctl),patch('bill_process_reader.os.set_blocking'),patch('bill_process_reader.os.write',side_effect=lambda fd,b:sent.append(b) or len(b)),patch('bill_process_reader.time.monotonic',side_effect=[0,1,1.05,1.1]),patch('bill_process_reader.time.sleep',side_effect=sleep):
            with self.assertRaises(InterruptedError):sample(123,456,True,False,5)
        packets=[FRAME.unpack(p) for p in sent]
        self.assertEqual([bool(p[-1]&1) for p in packets],[False,True,False])
