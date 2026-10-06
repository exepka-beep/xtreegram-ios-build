#!/usr/bin/env python3
"""Bake our own MTProto server public key into the Telegram-iOS client.

Why this is required
--------------------
The MTProto handshake only succeeds when the client knows a public key whose
fingerprint the server advertises in ``resPQ.server_public_key_fingerprints``.
``MTDatacenterAuthMessageService.defaultPublicKeys()`` ships two stock Telegram
keys, so against a self-hosted server the lookup in ``selectPublicKey`` returns
nil, ``req_DH_params`` is never sent, and the client keeps restarting the
handshake. The app then stays on the launch screen forever (black in dark mode).

The server side (gramsrv/telesrv) uses its own RSA identity — see
``TELESRV_RSA_IDENTITY_MODE`` in deploy/docker/docker-entrypoint.sh — so its
fingerprint must be compiled into every client. Android builds get it from the
patched tgnet key list; this script does the equivalent for iOS.

Usage
-----
    apply_rsa_key.py <telegram-ios-source-dir> <server-public-key.pem>

The PEM may be either SubjectPublicKeyInfo (``BEGIN PUBLIC KEY``, what
``openssl rsa -pubout`` prints) or PKCS#1 (``BEGIN RSA PUBLIC KEY``).
"""

import base64
import hashlib
import pathlib
import re
import sys

TARGET = "submodules/MtProtoKit/Sources/MTDatacenterAuthMessageService.m"
BEGIN = "-----BEGIN RSA PUBLIC KEY-----"
END = "-----END RSA PUBLIC KEY-----"

# Fingerprints of the two stock keys inside defaultPublicKeys(). Used both to
# prove we found the right blocks and to assert we replaced something.
STOCK_FINGERPRINTS = {
    0xB25898DF208D2603,  # testingPublicKeys
    0xD09D1D85DE64FD85,  # productionPublicKeys
}


def _der_ints(der):
    """PKCS#1 RSAPublicKey -> (n, e) as minimal big-endian bytes."""
    if der[0] != 0x30:
        raise ValueError("not an ASN.1 SEQUENCE")
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    out = []
    for _ in range(2):
        if der[i] != 0x02:
            raise ValueError("expected an ASN.1 INTEGER")
        i += 1
        length = der[i]
        i += 1
        if length & 0x80:
            count = length & 0x7F
            length = int.from_bytes(der[i:i + count], "big")
            i += count
        value = der[i:i + length]
        i += length
        while len(value) > 1 and value[0] == 0:
            value = value[1:]
        out.append(value)
    return out[0], out[1]


def _to_pkcs1(der):
    """Accept PKCS#1 or SPKI; return the PKCS#1 DER blob."""
    for offset in range(len(der)):
        if der[offset] != 0x30:
            continue
        try:
            n, e = _der_ints(der[offset:])
        except Exception:
            continue
        if len(n) == 256 and e == b"\x01\x00\x01":
            header = 2 + (der[offset + 1] & 0x7F) if der[offset + 1] & 0x80 else 2
            return der[offset:offset + header + int.from_bytes(der[offset + 2:offset + header], "big")]
    raise ValueError("no 2048-bit RSA public key found in the PEM")


def _tl_bytes(value):
    if len(value) < 254:
        head = bytes([len(value)])
    else:
        head = b"\xfe" + len(value).to_bytes(3, "little")
    body = head + value
    return body + b"\x00" * ((4 - len(body) % 4) % 4)


def fingerprint_from_base64(b64):
    """MTProto RSA fingerprint: SHA1 over TL(n) || TL(e), bytes 12..20 LE."""
    der = _to_pkcs1(base64.b64decode("".join(b64.split())))
    n, e = _der_ints(der)
    digest = hashlib.sha1(_tl_bytes(n) + _tl_bytes(e)).digest()
    return int.from_bytes(digest[12:20], "little")


def read_text_raw(path):
    """Read without newline translation so line endings survive untouched."""
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write_text_raw(path, text):
    """Write with LF only; a stray CRLF would break the patch tooling."""
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def load_key(path):
    text = read_text_raw(path)
    body = "".join(re.findall(r"^(?!-----)([A-Za-z0-9+/=]+)$", text, re.M))
    if not body:
        raise SystemExit("no base64 payload found in %s" % path)
    der = _to_pkcs1(base64.b64decode(body))
    return base64.b64encode(der).decode(), fingerprint_from_base64(body)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    source_dir = pathlib.Path(sys.argv[1])
    target = source_dir / TARGET
    if not target.is_file():
        raise SystemExit("not found: %s" % target)

    new_b64, new_fp = load_key(sys.argv[2])
    chunks = [new_b64[i:i + 64] for i in range(0, len(new_b64), 64)]
    print("server key fingerprint: 0x%016x (%d base64 chars, %d lines)"
          % (new_fp, len(new_b64), len(chunks)))

    text = read_text_raw(target)
    replaced = 0
    cursor = 0
    while True:
        start = text.find(BEGIN, cursor)
        if start < 0:
            break
        stop = text.find(END, start)
        if stop < 0:
            raise SystemExit("unterminated PEM block in %s" % TARGET)
        stop += len(END)
        region = text[start:stop]

        literals = list(re.finditer(r'"([A-Za-z0-9+/=]+)\\n"', region))
        if not literals:
            cursor = stop
            continue

        old_b64 = "".join(m.group(1) for m in literals)
        if fingerprint_from_base64(old_b64) not in STOCK_FINGERPRINTS:
            cursor = stop
            continue
        if len(literals) != len(chunks):
            raise SystemExit("line count mismatch: file has %d, key has %d"
                             % (len(literals), len(chunks)))
        for match, chunk in zip(literals, chunks):
            if len(match.group(1)) != len(chunk):
                raise SystemExit("line length mismatch inside %s" % TARGET)

        # Rebuild the region right-to-left so earlier offsets stay valid.
        for match, chunk in reversed(list(zip(literals, chunks))):
            region = region[:match.start(1)] + chunk + region[match.end(1):]
        text = text[:start] + region + text[stop:]
        replaced += 1
        cursor = start + len(region)

    if replaced != 2:
        raise SystemExit("expected to replace 2 key blocks, replaced %d" % replaced)

    write_text_raw(target, text)
    print("patched %d key block(s) in %s" % (replaced, TARGET))


if __name__ == "__main__":
    main()
