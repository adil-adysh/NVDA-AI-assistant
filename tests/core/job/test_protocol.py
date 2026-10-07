# -*- coding: utf-8 -*-
"""Unit tests for Wire Protocol, Framing, and Handshake Negotiation (Invariants A17, A18, A20)."""

from __future__ import annotations

import unittest

from tests.support import load_addon_module

dto_mod = load_addon_module("core.job.dto")
proto_mod = load_addon_module("core.job.protocol")

HandshakeRequest = dto_mod.HandshakeRequest

HEADER_SIZE = proto_mod.HEADER_SIZE
MAGIC = proto_mod.MAGIC
MAX_FRAME_SIZE = proto_mod.MAX_FRAME_SIZE
PROTOCOL_VERSION = proto_mod.PROTOCOL_VERSION
ErrorCode = proto_mod.ErrorCode
ProtocolError = proto_mod.ProtocolError

decode_binary_frame = proto_mod.decode_binary_frame
decode_ndjson_frame = proto_mod.decode_ndjson_frame
encode_binary_frame = proto_mod.encode_binary_frame
encode_ndjson_frame = proto_mod.encode_ndjson_frame
is_protocol_compatible = proto_mod.is_protocol_compatible
validate_handshake = proto_mod.validate_handshake


class TestNDJSONFraming(unittest.TestCase):
	"""Verify Newline-Delimited JSON control plane framing."""

	def test_encode_and_decode_valid_frame(self) -> None:
		payload = {"type": "job_submission", "job_id": "j-123", "generation": 1}
		raw = encode_ndjson_frame(payload)
		self.assertTrue(raw.endswith(b"\n"))

		decoded = decode_ndjson_frame(raw)
		self.assertEqual(decoded, payload)

	def test_unicode_preservation(self) -> None:
		payload = {"text": "Bonjour le monde! Привет мир! 🚀"}
		raw = encode_ndjson_frame(payload)
		decoded = decode_ndjson_frame(raw)
		self.assertEqual(decoded["text"], "Bonjour le monde! Привет мир! 🚀")

	def test_empty_frame_raises_protocol_error(self) -> None:
		with self.assertRaises(ProtocolError) as ctx:
			decode_ndjson_frame(b"   \n")
		self.assertEqual(ctx.exception.error_code, ErrorCode.INVALID_FRAME)

	def test_malformed_json_raises_protocol_error(self) -> None:
		with self.assertRaises(ProtocolError) as ctx:
			decode_ndjson_frame(b"{bad json\n")
		self.assertEqual(ctx.exception.error_code, ErrorCode.INVALID_FRAME)

	def test_frame_size_limit_exceeded(self) -> None:
		oversized = {"big": "x" * (MAX_FRAME_SIZE + 10)}
		with self.assertRaises(ProtocolError) as ctx:
			encode_ndjson_frame(oversized)
		self.assertEqual(ctx.exception.error_code, ErrorCode.FRAME_TOO_LARGE)

		huge_raw = b"x" * (MAX_FRAME_SIZE + 10)
		with self.assertRaises(ProtocolError) as ctx2:
			decode_ndjson_frame(huge_raw)
		self.assertEqual(ctx2.exception.error_code, ErrorCode.FRAME_TOO_LARGE)

	def test_non_dict_ndjson_frame_rejected(self) -> None:
		"""Verify that non-dict JSON primitives are rejected by decode_ndjson_frame."""
		primitives = [b"123\n", b'"a string"\n', b"[1, 2, 3]\n", b"true\n", b"false\n", b"null\n"]
		for raw in primitives:
			with self.assertRaises(ProtocolError) as ctx:
				decode_ndjson_frame(raw)
			self.assertEqual(ctx.exception.error_code, ErrorCode.INVALID_FRAME)
			self.assertIn("Frame payload must be a JSON object", str(ctx.exception))


class TestBinaryFraming(unittest.TestCase):
	"""Verify 12-byte header hybrid binary streaming framing."""

	def test_encode_and_decode_binary_frame(self) -> None:
		meta = {"session_id": "s1", "seq": 5}
		bin_payload = b"\x00\x01\x02\x03\xFF\xFE\xFD"
		frame = encode_binary_frame(meta, bin_payload)

		self.assertTrue(frame.startswith(MAGIC))
		self.assertGreaterEqual(len(frame), HEADER_SIZE + len(bin_payload))

		decoded_meta, decoded_bin = decode_binary_frame(frame)
		self.assertEqual(decoded_meta, meta)
		self.assertEqual(decoded_bin, bin_payload)

	def test_binary_frame_truncated_header(self) -> None:
		with self.assertRaises(ProtocolError) as ctx:
			decode_binary_frame(b"\xAA\x55")
		self.assertEqual(ctx.exception.error_code, ErrorCode.INVALID_FRAME)

	def test_binary_frame_invalid_magic(self) -> None:
		# 12 bytes of zeros
		bad_header = b"\x00" * 12
		with self.assertRaises(ProtocolError) as ctx:
			decode_binary_frame(bad_header)
		self.assertEqual(ctx.exception.error_code, ErrorCode.INVALID_FRAME)

	def test_binary_frame_length_mismatch(self) -> None:
		meta = {"id": "test"}
		bin_data = b"12345"
		frame = encode_binary_frame(meta, bin_data)
		truncated = frame[:-2]  # Remove 2 bytes from payload
		with self.assertRaises(ProtocolError) as ctx:
			decode_binary_frame(truncated)
		self.assertEqual(ctx.exception.error_code, ErrorCode.INVALID_FRAME)

	def test_non_dict_binary_frame_metadata_rejected(self) -> None:
		"""Verify that non-dict metadata JSON is rejected by decode_binary_frame."""
		import struct

		primitives = [b"123", b'"string"', b"[1, 2]", b"true"]
		for raw_meta in primitives:
			header = struct.pack(">4sII", MAGIC, len(raw_meta), 0)
			frame = header + raw_meta
			with self.assertRaises(ProtocolError) as ctx:
				decode_binary_frame(frame)
			self.assertEqual(ctx.exception.error_code, ErrorCode.INVALID_FRAME)
			self.assertIn("Frame payload must be a JSON object", str(ctx.exception))


class TestHandshakeNegotiation(unittest.TestCase):
	"""Verify protocol version compatibility logic and capability negotiation."""

	def test_protocol_compatibility(self) -> None:
		self.assertTrue(is_protocol_compatible("1.0.0", "1.0.0"))
		self.assertTrue(is_protocol_compatible("1.2.3", "1.0.0"))
		self.assertTrue(is_protocol_compatible("1.0.0", "1.9.9"))
		self.assertFalse(is_protocol_compatible("2.0.0", "1.0.0"))
		self.assertFalse(is_protocol_compatible("0.9.0", "1.0.0"))
		self.assertFalse(is_protocol_compatible("invalid", "1.0.0"))

	def test_validate_handshake_accepted(self) -> None:
		req = HandshakeRequest(
			protocol_version="1.0.0",
			client_pid=1000,
			requested_capabilities=("job.model_download", "job.inference", "unknown.capability"),
			request_id="req-test-1",
		)
		resp = validate_handshake(req, worker_version="1.0.0", worker_pid=2000)
		self.assertTrue(resp.accepted)
		self.assertEqual(resp.protocol_version, "1.0.0")
		self.assertEqual(resp.worker_pid, 2000)
		self.assertEqual(resp.correlation_id, "req-test-1")
		self.assertIn("job.model_download", resp.negotiated_capabilities)
		self.assertIn("job.inference", resp.negotiated_capabilities)
		self.assertNotIn("unknown.capability", resp.negotiated_capabilities)

	def test_validate_handshake_rejected_on_version_mismatch(self) -> None:
		req = HandshakeRequest(
			protocol_version="2.0.0",
			client_pid=1000,
			request_id="req-test-2",
		)
		resp = validate_handshake(req, worker_version="1.0.0", worker_pid=2000)
		self.assertFalse(resp.accepted)
		self.assertIsNotNone(resp.error_message)
		self.assertIn("Incompatible protocol version", resp.error_message)
		self.assertEqual(resp.correlation_id, "req-test-2")


class TestErrorCatalog(unittest.TestCase):
	"""Verify ErrorCode catalog completeness and ProtocolError exception wrapping."""

	def test_error_code_catalog(self) -> None:
		self.assertEqual(ErrorCode.PROTOCOL_VERSION_MISMATCH, "PROTOCOL_VERSION_MISMATCH")
		self.assertEqual(ErrorCode.FRAME_TOO_LARGE, "FRAME_TOO_LARGE")
		self.assertEqual(ErrorCode.CIRCUIT_BREAKER_TRIPPED, "CIRCUIT_BREAKER_TRIPPED")
		self.assertEqual(ErrorCode.PREEMPTION_TIMEOUT, "PREEMPTION_TIMEOUT")

	def test_protocol_error_fields(self) -> None:
		err = ProtocolError(
			ErrorCode.DOWNLOAD_FAILED,
			message="HTTP 404 Not Found",
			retriable=True,
			details={"url": "http://example.com/model.bin"},
		)
		self.assertEqual(err.error_code, ErrorCode.DOWNLOAD_FAILED)
		self.assertEqual(err.message, "HTTP 404 Not Found")
		self.assertTrue(err.retriable)
		self.assertEqual(err.details["url"], "http://example.com/model.bin")
		self.assertIn("[DOWNLOAD_FAILED]", str(err))


if __name__ == "__main__":
	unittest.main()
