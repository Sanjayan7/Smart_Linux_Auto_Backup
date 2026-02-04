import configparser
import os
from typing import List
from autobackup.models.backup_config import BackupConfig

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'backup.conf')

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
            'retention_policy': 'none', # Updated default
            'incremental': 'no',
            'compression': 'no',
            'encryption': 'no',
            'password': '',
            'schedule': '', # Cron format
            'backup_interval_days': '0', # New: 0 means no daily interval backup
            'backup_name_template': '{timestamp}',
            'notifications_enabled': 'no', # New default
            'cloud_enabled': 'no',
            'cloud_provider': 's3',
            'cloud_bucket': '',
            'cloud_region': 'us-east-1',
            'cloud_incremental': 'yes',
        }
        with open(CONFIG_FILE, 'w') as configfile:
            self._config.write(configfile)

    def get_backup_config(self) -> BackupConfig:
        defaults = self._config['DEFAULT']
        exclude_patterns_str = defaults.get('exclude_patterns', '')
        exclude_patterns: List[str] = [p.strip() for p in exclude_patterns_str.split(',')] if exclude_patterns_str else []

        return BackupConfig(
            source=defaults.get('source', ''),
            destination=defaults.get('destination', ''),
            exclude_patterns=exclude_patterns,
            retention_policy=defaults.get('retention_policy', 'none'),
            incremental=defaults.getboolean('incremental', False),
            compression=defaults.getboolean('compression', False),
            encryption=defaults.getboolean('encryption', False),
            password=defaults.get('password', ''),
            schedule=defaults.get('schedule', ''),
            backup_interval_days=defaults.getint('backup_interval_days', 0),
            backup_name_template=defaults.get('backup_name_template', '{timestamp}'),
            notifications_enabled=defaults.getboolean('notifications_enabled', False),
            cloud_enabled=defaults.getboolean('cloud_enabled', False),
            cloud_provider=defaults.get('cloud_provider', 's3'),
            cloud_bucket=defaults.get('cloud_bucket', ''),
            cloud_region=defaults.get('cloud_region', 'us-east-1'),
            cloud_incremental=defaults.getboolean('cloud_incremental', True)
        )

    def save_backup_config(self, config: BackupConfig):
        self._config['DEFAULT'] = {
            'source': config.source,
            'destination': config.destination,
            'exclude_patterns': ','.join(config.exclude_patterns),
            'retention_policy': config.retention_policy,
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
            'cloud_bucket': config.cloud_bucket,
            'cloud_region': config.cloud_region,
            'cloud_incremental': 'yes' if config.cloud_incremental else 'no'
        }
        with open(CONFIG_FILE, 'w') as configfile:
            self._config.write(configfile)

settings = Settings()
