
import configparser
import os
import json
from typing import List, Optional
from autobackup.models.backup_config import BackupConfig

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'backup.conf')
JSON_CONFIG_PATH = os.path.expanduser("~/.config/autobackup/config.json")

class Settings:
    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
            cls._config = configparser.ConfigParser()
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            self._config.read(CONFIG_FILE)
        else:
            self._create_default_config()
            self._config.read(CONFIG_FILE) # Read newly created default

    def _create_default_config(self):
        self._config['DEFAULT'] = {
            'source': '/home/sanjayan/Arch_Proj/my_important_data/',
            'destination': '/home/sanjayan/Arch_Proj/my_backup_storage/',
            'exclude_patterns': '', # Comma-separated
            'retention_policy': 'none',
            'local_enabled': 'yes',
            'incremental': 'no',
            'compression': 'no',
            'encryption': 'no',
            'password': '',
            'schedule': '', # Cron format
            'backup_interval_days': '0',
            'backup_name_template': '{timestamp}',
            'notifications_enabled': 'no',
            'cloud_enabled': 'no',
            'cloud_provider': 'rclone',
            'cloud_archive': 'yes',
            'retention_enabled': 'no',
            'retention_count': '5',
        }
        with open(CONFIG_FILE, 'w') as configfile:
            self._config.write(configfile)

    def _load_json_config(self) -> dict:
        if os.path.exists(JSON_CONFIG_PATH):
            try:
                with open(JSON_CONFIG_PATH, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_json_config(self, data: dict):
        os.makedirs(os.path.dirname(JSON_CONFIG_PATH), exist_ok=True)
        try:
            with open(JSON_CONFIG_PATH, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def get_backup_config(self) -> BackupConfig:
        defaults = self._config['DEFAULT']
        exclude_patterns_str = defaults.get('exclude_patterns', '')
        exclude_patterns: List[str] = [p.strip() for p in exclude_patterns_str.split(',')] if exclude_patterns_str else []

        json_cfg = self._load_json_config()

        return BackupConfig(
            source=defaults.get('source', ''),
            destination=defaults.get('destination', ''),
            exclude_patterns=exclude_patterns,
            retention_policy=defaults.get('retention_policy', 'none'),
            local_enabled=defaults.getboolean('local_enabled', True),
            incremental=defaults.getboolean('incremental', False),
            compression=defaults.getboolean('compression', False),
            encryption=defaults.getboolean('encryption', False),
            password=defaults.get('password', ''),
            schedule=defaults.get('schedule', ''),
            backup_interval_days=defaults.getint('backup_interval_days', 0),
            backup_name_template=defaults.get('backup_name_template', '{timestamp}'),
            notifications_enabled=defaults.getboolean('notifications_enabled', False),
            cloud_enabled=json_cfg.get('cloud_enabled', defaults.getboolean('cloud_enabled', False)),
            cloud_provider=json_cfg.get('cloud_provider', defaults.get('cloud_provider', 'rclone')),
            rclone_remote=json_cfg.get('rclone_remote', None),
            cloud_archive=json_cfg.get('cloud_archive', defaults.getboolean('cloud_archive', True)),
            retention_enabled=json_cfg.get('retention_enabled', defaults.getboolean('retention_enabled', fallback=False)),
            retention_count=json_cfg.get('retention_count', defaults.getint('retention_count', fallback=5)),
            scheduler_enabled=json_cfg.get('scheduler_enabled', False),
            scheduler_frequency=json_cfg.get('scheduler_frequency', 'daily'),
            scheduler_time=json_cfg.get('scheduler_time', '22:00'),
            scheduler_day=json_cfg.get('scheduler_day', 'Sunday'),
            scheduler_interval_minutes=json_cfg.get('scheduler_interval_minutes', 60),
        )

    def save_backup_config(self, config: BackupConfig):
        self._config['DEFAULT'] = {
            'source': config.source,
            'destination': config.destination,
            'exclude_patterns': ','.join(config.exclude_patterns),
            'retention_policy': config.retention_policy,
            'local_enabled': 'yes' if config.local_enabled else 'no',
            'incremental': 'yes' if config.incremental else 'no',
            'compression': 'yes' if config.compression else 'no',
            'encryption': 'yes' if config.encryption else 'no',
            'password': config.password or '',
            'schedule': config.schedule or '',
            'backup_interval_days': str(config.backup_interval_days),
            'backup_name_template': config.backup_name_template,
            'notifications_enabled': 'yes' if config.notifications_enabled else 'no',
            'cloud_enabled': 'yes' if config.cloud_enabled else 'no',
            'cloud_provider': config.cloud_provider,
        }
        with open(CONFIG_FILE, 'w') as configfile:
            self._config.write(configfile)

        # Sync to JSON config as requested
        json_data = {
            "cloud_provider": config.cloud_provider,
            "rclone_remote": config.rclone_remote,
            "cloud_enabled": config.cloud_enabled,
            "cloud_archive": config.cloud_archive,
            "retention_enabled": config.retention_enabled,
            "retention_count": config.retention_count,
            "scheduler_enabled": config.scheduler_enabled,
            "scheduler_frequency": config.scheduler_frequency,
            "scheduler_time": config.scheduler_time,
            "scheduler_day": config.scheduler_day,
            "scheduler_interval_minutes": config.scheduler_interval_minutes,
        }
        self._save_json_config(json_data)

settings = Settings()
