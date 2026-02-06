# 🔐 Secure Cloud Credential Handling Strategy

**Role:** Security Engineer  
**Scope:** Linux Desktop Backup Application  
**Target:** AWS/Google Cloud Credentials protection

---

## 1. Executive Summary

**The Rule:** 🚫 **NEVER** store API Keys, Secret Access Keys, or Service Account Tokens in `settings.json`, SQLite, or log files.

**The Solution:** Use the Linux **Secret Service API** (via the `python-keyring` library) to store sensitive data. This leverages the operating system's native encrypted store (GNOME Keyring or KDE Wallet), which is unlocked automatically when the user logs into their desktop session.

---

## 2. Architecture: "The Vault Pattern"

We separate **Configuration** (non-sensitive) from **Secrets** (sensitive).

### Storage Separation
| Data Type | Storage Location | Encryption | Example |
| :--- | :--- | :--- | :--- |
| **Configuration** | `~/.config/autobackup/settings.json` | None (Plaintext) | Bucket Name, Region, Sync Interval |
| **Secrets** | **System Keyring** (DBus/SecretService) | **AES-256** (System Managed) | AWS Secret Key, Encryption Passwords |

### Workflow Diagram

```text
[User UI]
   │
   ├─ Enter Access Key ID -> [Settings Manager] -> saved to settings.json
   └─ Enter Secret Key    -> [Credential Manager] -> saved to System Keyring
                                    │
                                    ▼
                          [OS Secret Service]
                          (Encrypted with User Login Password)
```

---

## 3. Implementation Strategy

### A. Library Selection
We will use the **`keyring`** library. It is the de-facto standard for Python cross-platform keyring access.

```bash
pip install keyring
```

### B. Credential Management Logic

```python
import keyring

SERVICE_ID = "com.autobackup.linux.pro"

def save_cloud_credentials(provider: str, secret_key: str):
    """
    Securely save credentials to OS keyring.
    args:
        provider: 'aws_access_key' or 'google_token'
        secret_key: The sensitive string
    """
    # System handles encryption automatically
    keyring.set_password(SERVICE_ID, provider, secret_key)

def get_cloud_credentials(provider: str) -> str:
    """Retrieve credentials at runtime."""
    return keyring.get_password(SERVICE_ID, provider)
```

### C. UI/UX Changes
1.  **Input Fields:** Use `Show="*"` (masked input) for Secret Keys.
2.  **Memory Security:** Clear the variable from memory immediately after saving to keyring (though Python GC makes this tricky, minimizing scope helps).
3.  **Indication:** When loading the config form, show the Password/Key field as "Stored ✅" or "••••••••" instead of the actual characters. **Never** populate the text input with the retrieved password; only use it for the backend connection.

---

## 4. Cloud-Specific Best Practices (IAM)

Even with secure storage, the *keys themselves* should be limited in scope.

### Principle of Least Privilege
Advise users to create IAM Users with **Limited Scope Policy**:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:ListBucket", "s3:GetObject"],
            "Resource": [
                "arn:aws:s3:::my-backup-bucket",
                "arn:aws:s3:::my-backup-bucket/*"
            ]
        }
    ]
}
```
**Why?** If the desktop is compromised and keys are stolen, the attacker can only modify *that specific bucket*, not delete your entire AWS account infrastructure.

---

## 5. Security Checklist

-   [ ] **Dependency Check:** Ensure `dbus-python` and `SecretStorage` are installed (usually default on Ubuntu/Fedora).
-   [ ] **Fallback:** If a headless environment (no generic keyring available), fallback to prompting the user for env vars (never fallback to plaintext file storage).
-   [ ] **Logs:** usage of `logger.info(f"Key: {secret}")` is strictly prohibited. Scrub logs of any string matching high-entropy regex or known key patterns.

