import json
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Firebase
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)

db = firestore.client()

print("--- FIREBASE MARKERS DUMP ---")
docs = db.collection("markers").stream()

found_any = False
for doc in docs:
    found_any = True
    print(f"\nDocument ID: {doc.id}")
    # Added default=str to convert DatetimeWithNanoseconds and GeoPoints to text
    print(json.dumps(doc.to_dict(), indent=2, default=str))

if not found_any:
    print("No documents found in the 'markers' collection.")