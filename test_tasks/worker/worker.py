import time
import json
from datetime import datetime


class TaskWorker:
    def __init__(self):
        self.tasks = []
        self.running = False

    def process_task(self, task_data):
        """Mock task processing"""
        print(f"[{datetime.now()}] Processing task: {task_data}")
        time.sleep(2)  # Simulate work
        return {"status": "completed", "task": task_data}

    def start_worker(self):
        """Start the worker loop"""
        self.running = True
        print("Worker started. Processing tasks...")

        while self.running:
            if self.tasks:
                task = self.tasks.pop(0)
                result = self.process_task(task)
                print(f"Task completed: {json.dumps(result, indent=2)}")
            else:
                time.sleep(1)

    def stop_worker(self):
        """Stop the worker"""
        self.running = False
        print("Worker stopped.")


if __name__ == "__main__":
    worker = TaskWorker()
    # Add some mock tasks
    worker.tasks = ["task_1", "task_2", "task_3"]

    try:
        worker.start_worker()
    except KeyboardInterrupt:
        worker.stop_worker()