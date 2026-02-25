# Professional Encryption Design for AutoBackup

## 1. Why Archive-Level Encryption?

We have chosen **Archive-Level Encryption** (encrypting the final `.tar.gz` artifact) over file-level encryption (encrypting individual files) for the following security and efficiency reasons:

1.  **Metadata Protection**: Archive encryption hides the *contents* of the backup. With file-level encryption, the directory structure, filenames, and file sizes often remain visible (unless complex obfuscation is used). `backup.tar.gz.gpg` reveals only that a backup exists, not what is inside it.
2.  **Compression Efficiency**: Compression works best on similar data. Compressing *before* encryption yields significantly smaller archives. Encrypted data looks like random noise and is virtually incompressible.
    *   **Correct Flow**: Files -> Tar/Compression -> Encryption
    *   **Incorrect Flow**: Files -> Encryption -> Tar/Compression (Result is 0% compression)
3.  **Integrity**: GPG provides authenticated encryption. Verifying one signature covers the entire backup state, whereas file-level requires verifying thousands of individual signatures.
4.  **Leak Prevention**: File-level encryption often leaves temporary plain-text copies of files during the process if not careful. Archive-level encryption allows us to pipe the compressed stream directly into GPG (in advanced implementations) or strictly manage the single archive artifact.

## 2. Backup Flow with Encryption

This workflow ensures encryption applies *only* to the final artifact and strictly after incremental decisions.

1.  **Incremental Analysis**:
    *   System scans source.
    *   Compares with `backup_metadata.json` (stored unencrypted* to allow logic to work).
    *   Identifies Changed Files.
    *   *Security Note*: Metadata contains filenames/sizes/hashes. This is acceptable for the host system to function, but the *files content* in the archive will be secured.

2.  **Transfer & Organization**:
    *   `rsync` copies changed files to a temporary build directory (e.g., `dst/2026-02-06_10-00-00`).

3.  **Compression**:
    *   Create `dst/2026-02-06_10-00-00.tar.gz` from the build directory.
    *   Delete the build directory.

4.  **Encryption (The Secure Step)**:
    *   **Input**: `dst/2026-02-06_10-00-00.tar.gz`
    *   **Action**: Execute `gpg --symmetric --cipher-algo AES256 ...`
    *   **Output**: `dst/2026-02-06_10-00-00.tar.gz.gpg`

5.  **Cleanup**:
    *   **Secure Delete**: The unencrypted `.tar.gz` is immediately deleted.
    *   Only the `.gpg` file remains.

6.  **Metadata Update**:
    *   Update `backup_metadata.json` to reflect that the backup completed.

## 3. Restore Flow with Decryption

Decryption is **never** automatic. It happens only when the user explicitly requests a restore.

1.  **Selection**:
    *   User selects a backup version (e.g., `2026-02-06_10-00-00`).
    *   System detects `.gpg` extension.

2.  **Authentication**:
    *   UI prompts: "Enter decryption password for backup 2026-02-06_10-00-00".
    *   User inputs password (kept in memory, never saved).

3.  **Streaming Restore (Secure)**:
    *   The system constructs a pipeline:
        `gpg --decrypt (with password) -> PIPE -> tar --extract`
    *   **Benefit**: The unencrypted `.tar.gz` archive is NEVER written to disk. The plain files are extracted directly to the restore destination.

4.  **Safety**:
    *   If password is bad -> GPG fails -> Pipe closes -> Restore aborts.
    *   No cleanup of a massive 100GB decypted tarball is needed because it never existed.

## 4. GPG Commands

### Encryption
```bash
# --batch: non-interactive
# --yes: overwrite output
# --passphrase-fd 0: read password from stdin
gpg --symmetric \
    --cipher-algo AES256 \
    --batch --yes \
    --passphrase-fd 0 \
    --output "/path/to/backup.tar.gz.gpg" \
    "/path/to/backup.tar.gz"
```

### Streaming Decryption (Peek/List Content)
```bash
gpg --decrypt --batch --passphrase-fd 0 "/path/to/backup.tar.gz.gpg" | tar tvz
```

### Streaming Decryption (Restore)
```bash
gpg --decrypt --batch --passphrase-fd 0 "/path/to/backup.tar.gz.gpg" | tar xvz -C "/restore/destination"
```

## 5. UI/UX Recommendations

1.  **Backup Configuration**:
    *   Checkbox: `[x] Encrypt Backup`
    *   When checked, enable `Password` input field.
    *   **Warning Label**: "If you lose this password, your backup is unrecoverable."

2.  **Password Input**:
    *   Use a secure entry field (masked `********`).
    *   Do NOT offer "Remember this password" unless using system keyring (beyond scope, stick to manual for high security).

3.  **Restore Dialog**:
    *   When user clicks "Restore", check file type.
    *   If `.gpg`: Pop up modal "Unlock Backup".
    *   Status: "Decrypting and Restoring..." (Indeterminate progress or file counting).

## 6. Security Justification

*   **AES-256**: Industry standard, approved for Top Secret information (US Gov).
*   **GPG**: Battle-tested, open-source auditing, avoids implementing "rolled-your-own" crypto.
*   **Ephemeral Decryption**: By piping `gpg | tar`, we avoid the common security flaw of leaving a "temp_decrypted_full_backup.tar" file on the disk which might be recovered later by forensic tools.
*   **Separation**: Logic relies on unencrypted metadata (filenames) for speed/incremental decisions, keeping the heavy crypto operations strictly for the actual data content.

