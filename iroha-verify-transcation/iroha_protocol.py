"""Iroha-specific binary protocol builders and parsers."""

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scale_codec import decode_compact_u, encode_compact_u, encode_string


def parse_public_key(public_key: str) -> bytes:
    """Validate and decode an ed25519 public key from the ed0120-prefixed format."""
    normalized = public_key.strip()
    if not normalized.lower().startswith("ed0120"):
        raise ValueError("Only ed25519 public keys with ed0120 prefix are supported.")
    key_bytes = bytes.fromhex(normalized[6:])
    if len(key_bytes) != 32:
        raise ValueError("Public key payload must be 32 bytes.")
    return key_bytes


def normalize_tx_hash(tx_hash: str) -> bytes:
    """Normalize transaction hash to raw 32-byte representation."""
    normalized = tx_hash.strip().removeprefix("0x")
    digest = bytes.fromhex(normalized)
    if len(digest) != 32:
        raise ValueError("Transaction hash must be 32 bytes (64 hex chars).")
    return digest


def encode_account_id(authority: str) -> bytes:
    """Encode <public_key>@<domain> into Iroha AccountId SCALE bytes."""
    signatory, domain = authority.split("@", 1)
    public_key = parse_public_key(signatory)
    domain_id = encode_string(domain)
    public_key_struct = b"\x00" + encode_compact_u(len(public_key)) + public_key
    return domain_id + public_key_struct


def build_query_request_with_authority(authority: str, tx_hash: bytes) -> bytes:
    """Build QueryRequest::Start payload for FindTransactions by hash."""
    account_id = encode_account_id(authority)

    predicate = (
        b"\x00"  # CompoundPredicate::Atom
        + b"\x02"  # CommittedTransactionProjection::Value
        + b"\x01"  # SignedTransactionProjection::Hash
        + b"\x00"  # TransactionHashProjection::Atom
        + b"\x00"  # TransactionHashPredicateAtom::Equals
        + tx_hash  # HashOf<SignedTransaction>
    )
    selector = (
        encode_compact_u(2)
        + b"\x01\x00"  # BlockHash -> Atom
        + b"\x03\x00"  # Error -> Atom
    )
    # FindTransactions itself is a zero-sized type in this SCALE layout.
    query_with_filter = predicate + selector
    query_box = b"\x0d" + query_with_filter  # QueryBox::FindTransactions

    pagination = b"\x00" + (0).to_bytes(8, "little")  # limit=None, offset=0
    sorting = b"\x00"  # sort_by_metadata_key=None
    fetch_size = b"\x00"  # fetch_size=None
    query_params = pagination + sorting + fetch_size
    query_request = b"\x01" + query_box + query_params  # QueryRequest::Start
    return account_id + query_request


def build_signed_query(payload: bytes, signing_key: Ed25519PrivateKey) -> bytes:
    # Iroha signs HashOf<T>, not raw SCALE bytes.
    hashed_payload = bytearray(hashlib.blake2b(payload, digest_size=32).digest())
    hashed_payload[-1] |= 0x01
    signature = signing_key.sign(bytes(hashed_payload))
    signature_struct = encode_compact_u(len(signature)) + signature  # Signature { payload: Vec<u8> }
    signed_query_v1 = signature_struct + payload
    return b"\x01" + signed_query_v1  # SignedQuery::V1


def parse_query_response(data: bytes) -> tuple[str, str]:
    """Extract block hash and status from QueryResponse::Iterable bytes."""
    if not data:
        raise RuntimeError("Empty response body from /query.")

    cursor = 0
    variant = data[cursor]
    cursor += 1
    if variant != 1:  # QueryResponse::Iterable
        raise RuntimeError(f"Unexpected QueryResponse variant: {variant}")

    tuple_count, cursor = decode_compact_u(data, cursor)
    block_hash = "UNKNOWN"
    status = "UNKNOWN"

    for _ in range(tuple_count):
        box_variant = data[cursor]
        cursor += 1
        vec_len, cursor = decode_compact_u(data, cursor)
        if box_variant == 30 and vec_len > 0:  # BlockHeaderHash
            block_hash = data[cursor : cursor + 32].hex().upper()
            cursor += 32 * vec_len
        elif box_variant == 22 and vec_len > 0:  # Vec<Option<TransactionRejectionReason>>
            flag = data[cursor]
            cursor += 1
            status = "COMMITTED" if flag == 0 else "REJECTED"
            if flag != 0:
                # Keep unknown reject payload opaque for now.
                pass
        else:
            raise RuntimeError(f"Unexpected QueryOutputBatchBox variant: {box_variant}")

    # remaining_items: u64, continue_cursor: Option<ForwardCursor>
    cursor += 8
    if cursor < len(data):
        _ = data[cursor]
    return block_hash, status
