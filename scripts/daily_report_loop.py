import asyncio
import sys
from datetime import datetime, timezone
from daily_report import generate_daily_report
import os

class LoggerWriter:
    def __init__(self, filepath):
        self.filepath = filepath
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)

    def write(self, message):
        if message.strip() == "":
            return
        with open(self.filepath, "a", encoding="utf-8") as f:
            timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            for line in message.splitlines():
                if line:
                    f.write(f"[{timestamp}] {line}\n")
            f.flush()
        sys.__stdout__.write(message)
        sys.__stdout__.flush()

    def flush(self):
        sys.__stdout__.flush()

async def main():
    sys.stdout = LoggerWriter("/app/logs/daily_reports.log")
    while True:
        try:
            await generate_daily_report()
        except Exception as e:
            print(f"Error generating report: {e}")
        
        # Sleep for 24 hours (86400 seconds)
        await asyncio.sleep(86400)

if __name__ == "__main__":
    asyncio.run(main())
