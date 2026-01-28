from autobackup.ui.main_window import MainWindow
from autobackup.utils.logger import logger

def main():
    logger.info("AutoBackup application started.")
    app = MainWindow()
    app.mainloop()
    logger.info("AutoBackup application closed.")

if __name__ == "__main__":
    main()
