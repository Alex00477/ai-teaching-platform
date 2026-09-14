"""Create one registration invite and print the plaintext once."""

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api", "src"))

from teaching_platform.db import get_session_factory
from teaching_platform.models import RegistrationCode
from teaching_platform.security import generate_one_time_code, hash_token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["student", "teacher"])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-uses", type=int, default=20)
    args = parser.parse_args()
    if args.days <= 0 or args.max_uses <= 0:
        raise SystemExit("days and max-uses must be positive")

    code = generate_one_time_code(f"{args.role[:3]}-invite")
    now = datetime.now(UTC)
    db = get_session_factory()()
    try:
        db.add(
            RegistrationCode(
                id=str(uuid4()),
                code_hash=hash_token(code),
                role=args.role,
                expires_at=now + timedelta(days=args.days),
                max_uses=args.max_uses,
            )
        )
        db.commit()
    finally:
        db.close()
    print(code)


if __name__ == "__main__":
    main()
