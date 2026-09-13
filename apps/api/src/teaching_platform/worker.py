import argparse
import time

from .config import get_settings, validate_worker_settings


def run_once() -> None:
    settings = get_settings()
    validate_worker_settings(settings)
    # Task polling is intentionally a placeholder until the database model exists.
    print(f"worker ready; poll_interval_seconds={settings.worker_poll_interval_seconds:g}")


def run_forever() -> None:
    settings = get_settings()
    validate_worker_settings(settings)
    print(f"worker started; poll_interval_seconds={settings.worker_poll_interval_seconds:g}")
    while True:
        # The persistent task table and claim transaction are added in the next step.
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

