import firebase_admin
from firebase_admin import credentials, firestore

def test_firebase_connection():
    try:
        print("1. Loading serviceAccountKey.json...")
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
        
        db = firestore.client()
        print("   -> Service account authenticated successfully!")

        print("\n2. Connecting to Firestore 'landmarks' collection...")
        landmarks_ref = db.collection("landmarks")
        docs = list(landmarks_ref.stream())

        print("\n==================================================")
        print("FIREBASE CONNECTION SUCCESSFUL!")
        print("==================================================")
        print(f"Found {len(docs)} document(s) in 'landmarks':\n")

        for doc in docs:
            data = doc.to_dict()
            name = data.get("name", "Missing 'name' field")
            location = data.get("location", "Missing 'location' field")
            print(f" - Document ID: {doc.id}")
            print(f"   Name:        {name}")
            print(f"   Location:    {location}")
            print("-" * 30)

        if not docs:
            print("Notice: Connected successfully, but your 'landmarks' collection is currently empty.")

    except FileNotFoundError:
        print("\nERROR: 'serviceAccountKey.json' was not found.")
        print("Ensure the newly generated JSON key file is in the same folder as this script.")
    except Exception as e:
        print(f"\nERROR: Connection failed.")
        print(f"Details: {e}")

if __name__ == "__main__":
    test_firebase_connection()