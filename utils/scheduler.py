import schedule
import time

class SchedulerManager:
    def __init__(self):
        pass

    def start(self):
        schedule.every(3).hours.do(self.run_monitor)
        while True:
            schedule.run_pending()
            time.sleep(60)

    def run_monitor(self):
        pass
