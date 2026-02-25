# Smart Linux Auto Backup

Smart Linux Auto Backup is a secure and automated backup system built using Python for Linux systems.  
It provides local backup, cloud backup (Google Drive), encryption, compression, scheduling, retention management, and checksum verification.

This project focuses on reliability, data integrity, and ease of use.

---

## 🚀 Features

- Full Backup
- Incremental Backup
- Compression Support
- Password-Based Encryption
- Cloud Backup using Google Drive
- Cloud Restore
- Retention Policy (Keep last N backups)
- Backup History Panel
- Automatic Scheduler (Daily / Weekly / Custom)
- SHA256 Checksum Verification

---

## 🛠 Development Environment

- Operating System: Arch Linux
- IDE: VS Codium
- Python Version: 3.14
- Version Control: Git & GitHub

### VS Code Extensions Used

- ms-python.python
- ms-python.vscode-pylance
- ms-python.debugpy
- ms-python.vscode-python-envs
- github.copilot-chat

(Java extensions were installed in the editor but not used in this project.)

---

## 📦 Installation

### 1️⃣ Clone Repository

``bash
git clone https://github.com/Sanjayan7/Smart_Linux_Auto_Backup.git
cd Smart_Linux_Auto_Backup

2️⃣ Create Virtual Environment
python -m venv .venv
source .venv/bin/activate

3️⃣ Install Python Requirements
pip install -r requirements.txt
☁ Cloud Setup (Google Drive via rclone)
1️⃣ Install rclone (Arch Linux)
sudo pacman -S rclone
2️⃣ Configure Google Drive

Run:

rclone config

Follow these steps:

Select: n (New remote)

Name it: gdrive

Storage type: drive

Follow authentication steps in browser

Confirm configuration

After setup, test connection:

rclone lsd gdrive:

If it lists folders, configuration is successful.

▶️ Run the Application
python -m autobackup
🔐 Security & Integrity

Encryption protects backups using password-based encryption.

All backups generate a SHA256 checksum.

Checksum is verified before restore.

Cloud backups are stored as secure archive files.

📊 Backup Workflow

Select source folder

Choose Full or Incremental backup

Enable Compression or Encryption (optional)

Choose Local and/or Cloud backup

Start Backup

Restore supports both Local and Cloud backups.

📂 Project Structure
autobackup/
  core/
  cloud/
  ui/
  models/
  utils/
main.py
requirements.txt
🏷 Version

Current Version: v1.0

👨‍💻 Author

Developed by Sanjayan
Linux | Python | Cloud Backup System
