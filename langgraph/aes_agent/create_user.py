from __future__ import annotations

import argparse
import getpass

from aes_agent.auth import AuthenticationError, get_auth_service


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an AES Workbench user in PostgreSQL."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", default="")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match.")

    try:
        user = get_auth_service().create_user(
            username=args.username,
            display_name=args.display_name,
            password=password,
        )
    except AuthenticationError as exc:
        parser.error(str(exc))

    print(f"Created AES user '{user.username}' ({user.id}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
