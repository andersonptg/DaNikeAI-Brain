import firebase_admin
from firebase_admin import firestore

PROJECT_ID = "da-nike-films"

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": PROJECT_ID})

db = firestore.client()

usuarios = db.collection("usuarios").stream()

total = 0

for usuario in usuarios:
    uid = usuario.id
    dispositivos = list(
        db.collection("usuarios")
        .document(uid)
        .collection("dispositivos")
        .stream()
    )

    quantidade = sum(
        1 for doc in dispositivos
        if (doc.to_dict() or {}).get("token")
    )

    if quantidade > 0:
        print(f"UID: {uid} | dispositivos: {quantidade}")
        total += 1

print(f"Total de usuários com FCM: {total}")
