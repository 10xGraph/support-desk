"""Print a JWT the API accepts, for one user, role and tenant (nothing else is printed).

Usage:
    .venv/bin/python deploy/scripts/make_token.py alice --name "Alice Chen" --org acme
    .venv/bin/python deploy/scripts/make_token.py sam --name "Sam Lee" --role support --org globex

Claims match what the API reads: `user_id`, `name` (the support agent greets the customer by it),
`roles` (the `auth.roles` names in 10xgraph.json), `org_id` (the `auth.tenant_claims` entry) and
`jti` (so one token can be revoked on its own).
Reads JWT_SECRET_KEY and JWT_ALGORITHM from .env.
"""

import argparse
import os
import time
import uuid

import jwt
from dotenv import load_dotenv


ROLES = ("member", "support", "org_admin", "admin")
ORGS = ("acme", "globex")

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument("user_id")
parser.add_argument("--role", choices=ROLES, default="member")
parser.add_argument("--org", choices=ORGS, required=True)
parser.add_argument("--ttl-hours", type=float, default=24)
parser.add_argument(
    "--name", help="display name the support agent greets (default: the user id, capitalised)"
)
args = parser.parse_args()

load_dotenv()  # reads .env; nothing from it is printed
secret = os.environ["JWT_SECRET_KEY"]
algorithm = os.getenv("JWT_ALGORITHM", "HS256")

now = int(time.time())
claims = {
    "user_id": args.user_id,
    "name": args.name or args.user_id.capitalize(),
    "roles": [args.role],
    "org_id": args.org,
    "jti": uuid.uuid4().hex,
    "iat": now,
    "exp": now + int(args.ttl_hours * 3600),
}
print(jwt.encode(claims, secret, algorithm=algorithm))
