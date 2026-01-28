# How to Work with Encrypted Backups

## Understanding Encrypted Backups

When you enable **Encryption (GPG)** in AutoBackup, your files are encrypted using GPG (GNU Privacy Guard) to protect sensitive data.

### ⚠️ Important: You Cannot Open .gpg Files Directly

**Encrypted files have a `.gpg` extension and cannot be opened with normal applications like text editors, image viewers, etc.**

If you try to open a `.gpg` file directly, you'll see errors like:
- "Unsupported format"
- "Cannot open file"
- "File is corrupt"

**This is normal!** The files are encrypted and need to be decrypted first.

---

## How to Access Your Encrypted Files

### Option 1: Use the Restore Feature (Recommended)

1. Open AutoBackup: `python3 -m autobackup`
2. Click the **"Restore"** button
3. Select the backup version you want to restore from
4. Browse and select the files/folders you need
5. Enter your **decryption password** (the same password you used when backing up)
6. Choose a restore destination
7. Click **"Restore Selected"**

The files will be automatically decrypted and saved to your chosen location in their original format.

---

### Option 2: Manual Decryption with GPG Command

If you prefer command-line tools, you can decrypt files manually:

```bash
# Decrypt a single file
gpg --decrypt --output originalfile.txt encryptedfile.txt.gpg

# You'll be prompted for the password
```

To decrypt all files in a backup directory:

```bash
cd /path/to/backup/folder

# Decrypt all .gpg files
for file in *.gpg; do
    gpg --decrypt --output "${file%.gpg}" "$file"
done
```

---

## Best Practices

### ✅ DO:
- **Remember your password** - Without it, your files cannot be decrypted
- **Store your password securely** (e.g., password manager)
- **Test restore** after your first encrypted backup to verify it works
- **Use the Restore feature** for convenience

### ❌ DON'T:
- Don't try to open `.gpg` files directly with applications
- Don't lose your encryption password (files will be unrecoverable)
- Don't share encrypted backups without the password

---

## Encryption during Backup Process

When you run a backup with encryption enabled:

1. **Files are copied** to the destination using rsync
2. **Each file is encrypted** individually with GPG using your password
3. **Original (unencrypted) copies are deleted** from the backup folder
4. **Only .gpg files remain** in the backup destination

This means your backup contains only encrypted `.gpg` files, which are secure even if someone gains access to your backup storage.

---

## Quick Reference

| Action | Method |
|--------|--------|
| **Backup with encryption** | Enable "Encryption (GPG)" checkbox, enter password, click "Start Backup" |
| **Restore encrypted files** | Click "Restore" button, enter decryption password, select files |
| **Manual decryption** | Use `gpg --decrypt` command |
| **Check if backup is encrypted** | Look for `.gpg` file extensions in backup folder |

---

## Troubleshooting

**Q: I forgot my encryption password. Can I recover my files?**  
A: Unfortunately, no. GPG encryption is very secure - without the password, the files cannot be decrypted.

**Q: Why do files show "unsupported format" when I try to open them?**  
A: Because they are encrypted `.gpg` files. You must decrypt them first using the Restore feature or `gpg` command.

**Q: Can I use encryption with incremental backups?**  
A: The app automatically disables incremental (`--link-dest`) when encryption is enabled, as encrypted files cannot use hard links.

**Q: How secure is the encryption?**  
A: GPG uses strong encryption (AES-256 by default with symmetric encryption). Your files are very secure as long as you use a strong password.

---

## Summary

🔐 **Remember:** Encrypted files (`.gpg`) are protected and secure, but you MUST use the Restore feature or GPG commands to decrypt them before use. **Never lose your encryption password!**
