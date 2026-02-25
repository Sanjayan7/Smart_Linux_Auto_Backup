
# ☁️ Google Drive Integration Specification

**Role:** Senior Cloud Architect
**Project:** AutoBackup Professional
**Feature:** Google Drive Cloud Storage

---

## 1. High-Level Architecture
We will implement Google Drive as a **Pluggable Cloud Provider** alongside the existing S3 implementation.

### Key Components:
1.  **GoogleDriveProvider**: A concrete implementation of our `CloudProvider` abstract base class.
2.  **OAuth2 Authenticator**: Handles the secure "Log in with Google" flow without ever seeing the user's password.
3.  **MIME-Multipart Uploader**: Handles binary file transfer ensuring reliable uploads for large archives.

### Security Model (OAuth2)
Unlike AWS (which uses static keys), Google Drive uses **Tokens**:
- **Access Token**: Short-lived key (1 hour) to upload/download.
- **Refresh Token**: Long-lived key stored securely in the system keyring. Allows the app to get new Access Tokens automatically.
- **Scope**: `https://www.googleapis.com/auth/drive.file` (Recommended). This limits the app's access **ONLY** to files created by the app itself, protecting the user's other Drive files.

---

## 2. Cloud Upload Flow (Step-by-Step)

This flow executes **asynchronously** after the local backup finishes.

1.  **Trigger**: Local `tar.gz.gpg` creation completes successfully.
2.  **Check Config**: `config.cloud_provider == "google_drive"`.
3.  **Token Refresh**:
    - App checks for valid credentials in `CredentialManager`.
    - If expired, uses `Refresh Token` to get a new `Access Token` silently.
    - If no token, UI shows "⚠ Drive Disconnected" and aborts.
4.  **Folder Resolution**:
    - App queries Drive for a folder named `"AutoBackup_Pro"`.
    - If missing, creates it.
    - Caches the `Folder ID` (Google uses IDs, not paths).
5.  **Upload**:
    - Streaming upload of the encrypted `.gpg` file.
    - Metadata: `{ name: "2026-02-07_15-00.tar.gz.gpg", parents: [FolderID] }`.
6.  **Verification**:
    - Verify upload HTTP 200 OK.
    - Log: "Uploaded to Drive (ID: 1abc...)"

---

## 3. Cloud Restore Flow

1.  **Authentication**: Ensure valid session.
2.  **List**: Query Drive API: `q="name contains 'AutoBackup' and trashed=false"`.
3.  **Select**: User picks a timestamped archive.
4.  **Download**:
    - Use `MediaIoBaseDownload` to stream the file to a temporary local path (`/tmp/restore_pending.gpg`).
5.  **Handover**:
    - Pass the temp file path to `BackupManager.restore_items()`.
    - The existing logic prompts for the AES-256 password and decrypts it.

---

## 4. Google Authentication (OAuth) Explanation

To look professional, we avoid "Copy-Paste Token" flows. We use the **Local Server Flow**:

1.  **Setup**:
    - Developer (User) creates a Project in Google Cloud Console.
    - Enables "Google Drive API".
    - Downloads `credentials.json` (OAuth 2.0 Client ID).
    - Places this file in the app directory.

2.  **User Experience**:
    - User clicks **[ Connect Google Drive ]** in the app.
    - App launches valid local URL in default browser.
    - User signs in to Google and clicks "Allow".
    - Browser redirects to `localhost:xxxx` (handled by the app).
    - App captures the token and saves it securely.

---

## 5. Implementation Code Snippets

### A. Dependencies
```bash
pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

### B. GoogleDriveProvider Class

```python
from autobackup.cloud.base import CloudProvider
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io
import pickle
import os

class GoogleDriveProvider(CloudProvider):
    # Only access files created by this app
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
    def __init__(self, credentials_path: str, token_path: str):
        self.creds = None
        self.service = None
        
        # Load tokens
        if os.path.exists(token_path):
            with open(token_path, 'rb') as token:
                self.creds = pickle.load(token)
                
        # Refresh if needed
        if self.creds and self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
            
        if self.creds:
            self.service = build('drive', 'v3', credentials=self.creds)

    def authenticate_user(self, credentials_json: str, token_pickle: str):
        """Interactive login flow"""
        flow = InstalledAppFlow.from_client_secrets_file(
            credentials_json, self.SCOPES)
        self.creds = flow.run_local_server(port=0)
        
        # Save tokens
        with open(token_pickle, 'wb') as token:
            pickle.dump(self.creds, token)
            
        self.service = build('drive', 'v3', credentials=self.creds)
        return True

    def upload_file(self, local_path, remote_filename, progress_callback=None):
        if not self.service: return False
        
        # 1. Get/Create Folder
        folder_id = self._get_folder_id("AutoBackup_Pro")
        
        # 2. Upload
        file_metadata = {
            'name': remote_filename,
            'parents': [folder_id]
        }
        media = MediaFileUpload(local_path, resumable=True)
        
        # Execute upload (simplified sync version)
        request = self.service.files().create(body=file_metadata,
                                            media_body=media,
                                            fields='id')
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status and progress_callback:
                progress_callback(int(status.resumable_progress), status.total_size)
                
        return True

    def _get_folder_id(self, folder_name):
        # Implementation to search for folder by mimeType='application/vnd.google-apps.folder'
        # If not found, create it.
        pass
```

### C. UI Integration Hook (Pseudocode)

```python
# In main_window.py

def _on_cloud_provider_change(self):
    provider = self.cloud_provider_var.get()
    
    if provider == "s3":
        self.s3_frame.pack()
        self.gdrive_frame.pack_forget()
    elif provider == "gdrive":
        self.s3_frame.pack_forget()
        self.gdrive_frame.pack()

def _on_connect_gdrive(self):
    try:
        provider = GoogleDriveProvider(...)
        provider.authenticate_user(...)
        messagebox.showinfo("Success", "Google Drive Connected!")
        self.test_cloud_connection()
    except Exception as e:
        messagebox.showerror("Auth Error", str(e))
```

---

## 6. UI Text Recommendations

**Provider Selection:**
> **Cloud Provider:** `(•) Google Drive` `( ) AWS S3`

**Google Drive Panel:**
> **Status:** 🔴 Not Connected
> `[ Connect Google Drive Account ]`
> *Clicking this will open your browser to authorize access.*
> *We only access files created by AutoBackup.*

**Status Bar Messages:**
> "Authenticating with Google..."
> "Uploading to Drive: 45% (Encrypted)"
> "⚠ Drive Upload Skipped (No Internet)"
> "✓ Saved to Google Drive (AutoBackup_Pro/backup_2026...)"

---

## 7. Refactoring Strategy
To support multiple providers, `BackupManager` must be updated:

```python
# Factory Pattern
def _get_cloud_provider(self, config):
    if config.cloud_provider == "s3":
        return S3Provider(config.s3_creds)
    elif config.cloud_provider == "gdrive":
        return GoogleDriveProvider(config.gdrive_creds)
```
