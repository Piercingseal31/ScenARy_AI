import json
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

db = firestore.client()

for col_name in ["content", "pois"]:
    print(f"\n" + "=" * 50)
    print(f"COLLECTION: '{col_name}'")
    print("=" * 50)
    
    docs = db.collection(col_name).stream()
    found_any = False
    
    for doc in docs:
        found_any = True
        print(f"\nDocument ID: {doc.id}")
        print(json.dumps(doc.to_dict(), indent=2, default=str))
        
    if not found_any:
        print(f"  (Collection '{col_name}' is empty)")