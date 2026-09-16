import argparse
import time

from .ai_tasks import claim_next_task, process_task
from .config import get_settings, validate_worker_settings
from .db import get_session_factory
from .ph8 import PH8Client


def run_once() -> None:
    settings = get_settings()
    validate_worker_settings(settings)
    db = get_session_factory()()
    try:
        task = claim_next_task(db)
        if not task:
            print("worker idle; no pending tasks")
            return
        client = PH8Client(settings)
        try:
            process_task(db, task, client=client, settings=settings)
        finally:
            client.close()
        print(f"worker processed task={task.id} status={task.status}")
    finally:
        db.close()


def run_forever() -> None:
    settings = get_settings()
    validate_worker_settings(settings)
    print(f"worker started; poll_interval_seconds={settings.worker_poll_interval_seconds:g}")
    while True:
        run_once()
        time.sleep(settings.worker_poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI grading worker")
    parser.add_argument("--once", action="store_true", help="validate configuration and exit")
    args = parser.parse_args()
    if args.once:
        run_once()
    else:
        run_forever()


if __name__ == "__main__":
    main()
