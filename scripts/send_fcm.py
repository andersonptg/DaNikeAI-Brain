import os
import firebase_admin
from firebase_admin import credentials, firestore, messaging
from firebase_admin._messaging_utils import UnregisteredError

PROJECT_ID = "da-nike-films"

uid = os.environ["NOTIFICACAO_UID"]
tipo = os.environ["NOTIFICACAO_TIPO"]
titulo = os.environ["NOTIFICACAO_TITULO"]
texto = os.environ["NOTIFICACAO_TEXTO"]
remetente_uid = os.environ.get("NOTIFICACAO_REMETENTE_UID", "").strip()
fila_id = os.environ.get("NOTIFICACAO_FILA_ID", "").strip()

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={"projectId": PROJECT_ID})

db = firestore.client()

ref = (
    db.collection("usuarios")
    .document(uid)
    .collection("dispositivos")
)

docs = ref.stream()

dispositivos = []

for doc in docs:
    dados = doc.to_dict() or {}
    token = dados.get("token")

    if token:
        dispositivos.append((doc.reference, token))

if not dispositivos:
    raise SystemExit("Nenhum dispositivo FCM encontrado para esse usuário.")

enviados = 0
invalidos = 0

for doc_ref, token in dispositivos:
    mensagem = messaging.Message(
        data={
            "tipo": tipo,
            "titulo": titulo,
            "texto": texto,
            "remetenteUid": remetente_uid,
        },
        token=token,
        android=messaging.AndroidConfig(
            priority="high"
        ),
    )

    try:
        resposta = messaging.send(mensagem)

        enviados += 1

        print(f"FCM enviado com sucesso: {resposta}")

    except UnregisteredError:
        invalidos += 1

        print("Token FCM inválido/desregistrado. Removendo dispositivo...")

        try:
            doc_ref.delete()
            print(f"Dispositivo inválido removido: {doc_ref.id}")
        except Exception as erro:
            print(f"Erro ao remover dispositivo inválido: {erro}")

    except Exception as erro:
        print(f"Erro ao enviar FCM para um dispositivo: {erro}")

print(f"Total de dispositivos encontrados: {len(dispositivos)}")
print(f"Total enviados com sucesso: {enviados}")
print(f"Total de tokens inválidos removidos: {invalidos}")

if fila_id and enviados > 0:
    try:
        doc_ref = (
            db.collection("fila_notificacoes")
            .document(fila_id)
        )

        doc_ref.update({
            "enviada": True,
            "enviadaEm": firestore.SERVER_TIMESTAMP,
            "totalDispositivos": enviados
        })

        print(f"Fila marcada como enviada: {fila_id}")

    except Exception as erro:
        print(f"Erro ao marcar fila como enviada: {erro}")

elif fila_id:
    print(
        "AVISO: nenhum dispositivo recebeu a notificação; "
        "fila não foi marcada como enviada."
    )

else:
    print(
        "AVISO: fila_id não informado; "
        "fila não foi marcada."
    )
