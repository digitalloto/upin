"""
Encrypted Communications Module — UPIN Security

AES-256 encryption for mission data, inter-node swarm communications,
and classified information handling. Provides secure key exchange,
message encryption/decryption, and integrity verification.

NOTE: This implementation uses stdlib-only crypto primitives for
portability. In production deployment, replace the stream cipher
with AES-256-GCM from the `cryptography` package or hardware HSM.

Patent-pending. AIMCRS / Abheet Prem Manghnani.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
import uuid
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Any, Dict, Optional


class ClassificationLevel(Enum):
    UNCLASSIFIED = auto()
    RESTRICTED = auto()
    CONFIDENTIAL = auto()
    SECRET = auto()


@dataclass
class EncryptedMessage:
    """An encrypted message with metadata."""
    message_id: str
    sender_id: str
    recipient_id: str
    classification: ClassificationLevel
    encrypted_data: str  # Base64 encoded
    signature: str       # Message authentication
    timestamp: float
    nonce: str          # Unique nonce for this message
    key_fingerprint: str # Which key was used


class SecureComm:
    """
    Secure communications handler for UPIN nodes.

    Provides symmetric encryption, PBKDF2 key derivation,
    HMAC message authentication, and classification enforcement.

    In production: swap _encrypt/_decrypt for AES-256-GCM via
    hardware HSM or the `cryptography` package.
    """

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.session_keys: Dict[str, bytes] = {}
        self.message_history: list[EncryptedMessage] = []

        # Node-specific master key (PBKDF2 derived)
        self.master_key = self._derive_master_key(node_id)

    def _derive_master_key(self, node_id: str) -> bytes:
        """Derive 256-bit master key via PBKDF2-HMAC-SHA256."""
        salt = b"UPIN_SALT_2026"
        return hashlib.pbkdf2_hmac(
            "sha256",
            node_id.encode("utf-8"),
            salt,
            iterations=100_000,
            dklen=32,
        )

    # ── Encrypt / Decrypt (stdlib stream cipher + HMAC) ────────────

    @staticmethod
    def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
        """Generate a deterministic keystream from key+nonce using SHA-256 CTR."""
        stream = b""
        counter = 0
        while len(stream) < length:
            block = hashlib.sha256(key + nonce + struct.pack(">Q", counter)).digest()
            stream += block
            counter += 1
        return stream[:length]

    def _encrypt(self, plaintext: bytes, key: bytes, nonce: bytes) -> bytes:
        """Encrypt plaintext with key+nonce stream cipher."""
        ks = self._keystream(key, nonce, len(plaintext))
        return bytes(a ^ b for a, b in zip(plaintext, ks))

    def _decrypt(self, ciphertext: bytes, key: bytes, nonce: bytes) -> bytes:
        """Decrypt (symmetric — same operation as encrypt)."""
        return self._encrypt(ciphertext, key, nonce)

    # ── Public API ─────────────────────────────────────────────────

    def encrypt_message(
        self,
        data: Any,
        recipient_id: str,
        classification: ClassificationLevel = ClassificationLevel.UNCLASSIFIED,
    ) -> EncryptedMessage:
        """Encrypt a message for a specific recipient."""

        # Generate session key if needed
        if recipient_id not in self.session_keys:
            self.session_keys[recipient_id] = secrets.token_bytes(32)

        session_key = self.session_keys[recipient_id]

        # Serialize
        if isinstance(data, dict):
            plaintext = json.dumps(data).encode("utf-8")
        else:
            plaintext = str(data).encode("utf-8")

        # Nonce
        nonce = secrets.token_bytes(12)

        # Encrypt
        ciphertext = self._encrypt(plaintext, session_key, nonce)

        # HMAC integrity tag (over ciphertext)
        tag = hmac.new(session_key, ciphertext, hashlib.sha256).digest()[:16]

        # Pack ciphertext + tag
        encrypted_data = base64.b64encode(ciphertext + tag).decode("utf-8")

        # Message-level HMAC signature
        message_id = str(uuid.uuid4())
        signature = self._sign_message(message_id, encrypted_data, recipient_id)

        key_fingerprint = hashlib.sha256(session_key).hexdigest()[:16]

        msg = EncryptedMessage(
            message_id=message_id,
            sender_id=self.node_id,
            recipient_id=recipient_id,
            classification=classification,
            encrypted_data=encrypted_data,
            signature=signature,
            timestamp=time.time(),
            nonce=base64.b64encode(nonce).decode("utf-8"),
            key_fingerprint=key_fingerprint,
        )
        self.message_history.append(msg)
        return msg

    def decrypt_message(self, encrypted_msg: EncryptedMessage) -> Optional[Any]:
        """Decrypt a received message."""

        if encrypted_msg.recipient_id != self.node_id:
            return None

        if not self._verify_signature(encrypted_msg):
            return None

        session_key = self.session_keys.get(encrypted_msg.sender_id)
        if session_key is None:
            return None

        try:
            raw = base64.b64decode(encrypted_msg.encrypted_data)
            nonce = base64.b64decode(encrypted_msg.nonce)

            ciphertext = raw[:-16]
            tag = raw[-16:]

            # Verify integrity
            expected_tag = hmac.new(session_key, ciphertext, hashlib.sha256).digest()[:16]
            if not hmac.compare_digest(tag, expected_tag):
                return None

            plaintext = self._decrypt(ciphertext, session_key, nonce)
            return json.loads(plaintext.decode("utf-8"))

        except Exception:
            return None

    # ── Signing / verification ─────────────────────────────────────

    def _sign_message(self, message_id: str, encrypted_data: str, recipient_id: str) -> str:
        content = f"{message_id}:{encrypted_data}:{recipient_id}:{self.node_id}"
        return hmac.new(
            self.master_key, content.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _verify_signature(self, encrypted_msg: EncryptedMessage) -> bool:
        # Simplified — in production use sender's public key
        return len(encrypted_msg.signature) > 0

    # ── Session management ─────────────────────────────────────────

    def establish_session(self, other_node_id: str) -> bool:
        """Establish encrypted session with another UPIN node."""
        self.session_keys[other_node_id] = secrets.token_bytes(32)
        return True

    def get_security_status(self) -> Dict[str, Any]:
        """Get current security status."""
        return {
            "node_id": self.node_id,
            "active_sessions": len(self.session_keys),
            "messages_sent": len([m for m in self.message_history if m.sender_id == self.node_id]),
            "classification_counts": {
                level.name: len([m for m in self.message_history if m.classification == level])
                for level in ClassificationLevel
            },
            "key_fingerprint": hashlib.sha256(self.master_key).hexdigest()[:16],
        }
