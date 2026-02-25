"""
checksum.py
===========
SHA-256 checksum computation for backup integrity verification.

Uses chunked reading (1 MB) to avoid loading entire files into memory.
"""

import hashlib
import os

from autobackup.utils.logger import logger

CHUNK_SIZE = 1024 * 1024  # 1 MB


def compute_sha256(filepath: str) -> str:
    """
    Compute SHA-256 hex digest for a file using chunked reads.

    Parameters
    ----------
    filepath : str
        Absolute path to the file.

    Returns
    -------
    str
        64-character lowercase hex digest.

    Raises
    ------
    FileNotFoundError   if the file does not exist.
    OSError             on read errors.
    """
    sha = hashlib.sha256()
    size = os.path.getsize(filepath)

    logger.info(
        f"Computing SHA-256 for: {os.path.basename(filepath)} "
        f"({size / (1024**2):.2f} MB)"
    )

    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            sha.update(chunk)

    digest = sha.hexdigest()
    logger.info(f"SHA-256: {digest[:16]}...{digest[-8:]}")
    return digest


def verify_sha256(filepath: str, expected: str) -> bool:
    """
    Verify a file's SHA-256 against an expected digest.

    Parameters
    ----------
    filepath : str
        Path to file to check.
    expected : str
        Expected hex digest.

    Returns
    -------
    bool
        True if match, False if mismatch.
    """
    actual = compute_sha256(filepath)
    if actual == expected:
        logger.info(f"✓ Checksum verified: {os.path.basename(filepath)}")
        return True
    else:
        logger.error(
            f"✗ Checksum MISMATCH for {os.path.basename(filepath)}: "
            f"expected {expected[:16]}... got {actual[:16]}..."
        )
        return False
