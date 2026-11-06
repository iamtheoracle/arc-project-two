import socket
import struct
import threading
import unittest

from oracle_arc.orbits import EICAR, ClamdScanner, Orbits, ScanResult, SignatureScanner
from oracle_arc.types import MediaRejected, PermissionDenied, Principal, ToolUnavailable

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
U1, U2 = Principal("unibud", "u1"), Principal("unibud", "u2")


class Boom:
    name = "boom"

    def scan(self, data):
        raise RuntimeError("down")


class OrbitsTests(unittest.TestCase):
    def test_text_roundtrip_and_extraction(self):
        o = Orbits()
        a = o.ingest(U1, "notes.txt", "Lecture 1: thermodynamics".encode(), "text/plain")
        self.assertEqual((a.kind, a.status), ("text", "ready"))
        self.assertIn("thermodynamics", o.extract_text(U1, a.id))

    def test_csv_and_json_extraction(self):
        o = Orbits()
        c = o.ingest(U1, "t.csv", b"name,score\nada,9\n", "text/csv")
        self.assertIn("ada | 9", o.extract_text(U1, c.id))
        j = o.ingest(U1, "t.json", b'{"a":1}', "application/json")
        self.assertIn('"a": 1', o.extract_text(U1, j.id))

    def test_declared_type_must_match_real_bytes(self):
        with self.assertRaises(MediaRejected):
            Orbits().ingest(U1, "cat.png", b"just some text", "image/png")
        with self.assertRaises(MediaRejected):
            Orbits().ingest(U1, "notes.txt", PNG, "text/plain")

    def test_executables_scripts_archives_rejected_regardless_of_name(self):
        o = Orbits()
        for blob in (b"MZ\x90\x00" + b"\0" * 60, b"\x7fELF" + b"\0" * 60, b"#!/bin/sh\nrm -rf /", b"PK\x03\x04" + b"\0" * 30):
            with self.assertRaises(MediaRejected):
                o.ingest(U1, "holiday.jpg", blob, "")

    def test_size_limit_per_kind(self):
        o = Orbits(limits={"image": 40})
        with self.assertRaises(MediaRejected):
            o.ingest(U1, "big.png", PNG + b"0" * 100, "image/png")

    def test_eicar_blocked_by_builtin_scanner(self):
        with self.assertRaises(MediaRejected):
            Orbits().ingest(U1, "eicar.txt", EICAR, "text/plain")

    def test_scanner_failure_fails_closed(self):
        with self.assertRaises(MediaRejected) as c:
            Orbits(scanners=[Boom()]).ingest(U1, "a.txt", b"hello", "text/plain")
        self.assertIn("unavailable", str(c.exception))

    def test_required_scanner_must_have_run(self):
        with self.assertRaises(MediaRejected):
            Orbits(require_scanners=("clamd",)).ingest(U1, "a.txt", b"hello", "text/plain")

    def test_owner_only_access_and_deletion(self):
        o = Orbits()
        a = o.ingest(U1, "a.txt", b"private", "text/plain")
        with self.assertRaises(PermissionDenied):
            o.get(U2, a.id)
        with self.assertRaises(PermissionDenied):
            o.get(Principal("other", "u1"), a.id)
        o.delete(U1, a.id)
        with self.assertRaises(PermissionDenied):
            o.get(U1, a.id)

    def test_retention_sweep(self):
        t = [100.0]
        o = Orbits(retention_s=10, clock=lambda: t[0])
        a = o.ingest(U1, "a.txt", b"x", "text/plain")
        t[0] += 11
        self.assertEqual(o.sweep(), 1)
        with self.assertRaises(PermissionDenied):
            o.get(U1, a.id)

    def test_unprocessable_media_is_honestly_unavailable_until_a_processor_exists(self):
        o = Orbits()
        a = o.ingest(U1, "voice.wav", b"RIFF\0\0\0\0WAVE" + b"\0" * 40, "audio/wav")
        with self.assertRaises(ToolUnavailable):
            o.extract_text(U1, a.id)
        o.register_processor("audio", lambda data, mime: "transcript from a real processor")
        self.assertEqual(o.extract_text(U1, a.id), "transcript from a real processor")

    def test_clamd_instream_protocol(self):
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(2)
        port, seen = srv.getsockname()[1], []

        def serve():
            for verdict in (b"stream: OK\0", b"stream: Eicar-Test-Signature FOUND\0"):
                c, _ = srv.accept()
                buf = b""
                while True:
                    d = c.recv(65536)
                    buf += d
                    if buf.endswith(struct.pack("!I", 0)):
                        break
                seen.append(buf)
                c.sendall(verdict); c.close()
        threading.Thread(target=serve, daemon=True).start()
        sc = ClamdScanner("127.0.0.1", port)
        self.assertTrue(sc.scan(b"clean data").clean)
        r = sc.scan(b"bad data")
        self.assertFalse(r.clean)
        self.assertTrue(seen[0].startswith(b"zINSTREAM\0"))
        srv.close()


if __name__ == "__main__":
    unittest.main()
