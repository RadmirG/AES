from __future__ import annotations

import argparse
import getpass

from aes_agent.auth import AuthenticationError, get_auth_service


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset an AES Workbench user's password."
    )
    parser.add_argument("--username", required=True)
    args = parser.parse_args()

    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        parser.error("Passwords do not match.")

    try:
        user = get_auth_service().reset_password(
            username=args.username,
            password=password,
        )
    except AuthenticationError as exc:
        parser.error(str(exc))

    print(
        f"Reset password for AES user '{user.username}'. "
        "Active sessions were revoked."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
