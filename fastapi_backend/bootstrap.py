"""One-time atomic bootstrap for one Foodoo restaurant in its own GCP project.

Never exposes a public bootstrap HTTP endpoint; run as an authorized Cloud
Run Job or via a developer shell with Firestore credentials.
"""
import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import firestore
from pwdlib import PasswordHash

load_dotenv(Path(__file__).resolve().parent / ".env")

parser=argparse.ArgumentParser()
parser.add_argument("--restaurant-id",required=True)
parser.add_argument("--restaurant-name",required=True)
parser.add_argument("--admin-username",required=True)
args=parser.parse_args()

if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", args.restaurant_id):
    parser.error("restaurant-id must be 2-63 lowercase letters, numbers or hyphens, starting with a letter")
if not re.fullmatch(r"[a-zA-Z0-9._-]{2,150}", args.admin_username):
    parser.error("admin-username contains invalid characters")
if not args.restaurant_name.strip():
    parser.error("restaurant-name cannot be empty")
project=os.getenv("FOODOO_FIRESTORE_PROJECT")
if not project:
    raise SystemExit("FOODOO_FIRESTORE_PROJECT is required: refusing to bootstrap an implicit project")
password=os.getenv("FOODOO_INITIAL_ADMIN_PASSWORD")
if not password or len(password)<10:
    raise SystemExit("Provide FOODOO_INITIAL_ADMIN_PASSWORD (at least 10 characters) via a secret")
db=firestore.Client(project=project,database=os.getenv("FOODOO_FIRESTORE_DATABASE","(default)"))
restaurant=db.collection("restaurants").document(args.restaurant_id)
identity=db.collection("identities").document(args.admin_username.casefold())
profile={"name":args.restaurant_name.strip(),"address":"","contact_phone":"","gstin":"",
         "branch_type":"main","branch_name":"Main","branch_code":"main",
         "logo_data":"","fssai_license_number":"","cgst_rate":"2.50","sgst_rate":"2.50"}
account={"username":args.admin_username,"first_name":"","role":"admin","active":True,
         "restaurant_id":args.restaurant_id,"password_hash":PasswordHash.recommended().hash(password)}

@firestore.transactional
def provision(transaction):
    # Read both records before writes; either BOTH are created, or none.
    existing_restaurant=restaurant.get(transaction=transaction)
    existing_identity=identity.get(transaction=transaction)
    if existing_restaurant.exists or existing_identity.exists:
        raise SystemExit("Restaurant/admin already exists; bootstrap refuses to overwrite")
    transaction.create(restaurant,profile)
    transaction.create(identity,account)

provision(db.transaction())
print("Foodoo restaurant and administrator created atomically in project:",project)
