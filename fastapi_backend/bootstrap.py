"""One-time CLI for local/emulator tenant bootstrap; never run on existing data blindly."""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import firestore
from google.api_core.exceptions import AlreadyExists
from pwdlib import PasswordHash

load_dotenv(Path(__file__).resolve().parent / ".env")

parser=argparse.ArgumentParser()
parser.add_argument("--restaurant-id",required=True)
parser.add_argument("--restaurant-name",required=True)
parser.add_argument("--admin-username",required=True)
args=parser.parse_args()
password=os.getenv("FOODOO_INITIAL_ADMIN_PASSWORD")
if not password or len(password)<10:
    raise SystemExit("Set FOODOO_INITIAL_ADMIN_PASSWORD (minimum 10 characters) in the shell")
db=firestore.Client(project=os.getenv("FOODOO_FIRESTORE_PROJECT"),
                    database=os.getenv("FOODOO_FIRESTORE_DATABASE","(default)"))
restaurant=db.collection("restaurants").document(args.restaurant_id)
identity=db.collection("identities").document(args.admin_username.casefold())
if restaurant.get().exists or identity.get().exists:
    raise SystemExit("Existing restaurant or username; refusing to overwrite")
try:
    restaurant.create({"name":args.restaurant_name,"address":"","contact_phone":"","gstin":"",
                       "branch_type":"main","branch_name":"Main","branch_code":"main",
                       "logo_data":"","fssai_license_number":"","cgst_rate":"2.50","sgst_rate":"2.50"})
    identity.create({"username":args.admin_username,"first_name":"","role":"admin","active":True,
                     "restaurant_id":args.restaurant_id,"password_hash":PasswordHash.recommended().hash(password)})
except AlreadyExists:
    raise SystemExit("Bootstrap conflict; inspect Firestore before retrying")
print("Bootstrapped tenant and administrator account.")
