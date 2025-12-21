from fastapi import FastAPI, Form, Depends, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import func
from twilio.twiml.messaging_response import MessagingResponse
import urllib.parse 
import datetime
import os
import sys

# --- CONFIGURACIÓN DATABASE ---
# Forzamos tabla nueva (v3) para limpiar errores de esquema previos
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://usuario:password@localhost/dbname")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODELO DB ---
class Reserva(Base):
    __tablename__ = "reservas_v3"  # <--- CAMBIO IMPORTANTE: TABLA LIMPIA
    
    id = Column(Integer, primary_key=True, index=True)
    whatsapp_id = Column(String, index=True)
    nombre_completo = Column(String)
    tipo_entrada = Column(String) 
    cantidad = Column(Integer)
    confirmada = Column(Boolean, default=False)
    fecha_reserva = Column(DateTime, default=datetime.datetime.utcnow)
    rrpp_asignado = Column(String, default="Organico")

# Creamos la tabla nueva
Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()

# --- DIRECTORIO RRPP ---
DIRECTORIO_RRPP = {
    "matias": {"nombre": "Matias (RRPP)", "celular": "5491111111111"},
    "sofia":  {"nombre": "Sofia (RRPP)", "celular": "5491122222222"},
    "general": {"nombre": "Soporte General", "celular": "5491133333333"}
}

# --- MEMORIA GLOBAL ---
conversational_state = {}
temp_data = {}
user_attribution = {} 
ADMIN_PASSWORD = "Moscu123"
CUPO_TOTAL = 150

@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...), db: Session = Depends(get_db)):
    
    # Declaramos globales para poder resetearlas
    global conversational_state, temp_data
    
    sender = From
    incoming_msg = Body.strip()
    msg_lower = incoming_msg.lower()
    
    # LOG DE DEBUG: Esto aparecerá en el dashboard de Render si algo falla
    print(f"DEBUG: Mensaje recibido de {sender}: {incoming_msg}")
    
    resp = MessagingResponse()
    msg = resp.message()

    # --- 🚨 BOTÓN DE PÁNICO NUCLEAR ---
    # Si escribis cualquiera de estas palabras, el bot se resetea.
    palabras_escape = ["salir", "exit", "basta", "menu", "reset", "inicio"]
    
    # Chequeamos si la palabra exacta es una de escape, o si empieza con "salir"
    if msg_lower in palabras_escape or msg_lower.startswith("salir"):
        conversational_state[sender] = 'start'
        temp_data[sender] = {}
        msg.body("🔄 *SISTEMA REINICIADO*\n\nVolviste al menú principal de clientes.")
        return Response(content=str(resp), media_type="application/xml")

    # --- COMANDO ADMIN RESET (Modo Dios) ---
    if msg_lower == "admin reset":
        db.query(Reserva).delete()
        db.commit()
        conversational_state = {} # Borra memoria de TODOS
        temp_data = {}
        msg.body("🗑️ *FACTORY RESET V5*\n\n- Base de Datos (v3) Limpia.\n- Memoria RAM Limpia.\n- Sistema Listo.")
        return Response(content=str(resp), media_type="application/xml")

    # --- ATRIBUCIÓN DE RRPP (Se ejecuta siempre antes) ---
    rrpp_detectado = "Organico"
    if "vengo de" in msg_lower:
        partes = msg_lower.split("vengo de ")
        if len(partes) > 1:
            posible_nombre = partes[1].strip().split(" ")[0]
            if posible_nombre in DIRECTORIO_RRPP:
                user_attribution[sender] = posible_nombre
                rrpp_detectado = posible_nombre
                temp_data[sender] = {'rrpp_origen': posible_nombre}
    
    if sender in user_attribution:
        rrpp_detectado = user_attribution[sender]


    # --- MÁQUINA DE ESTADOS ---
    state = conversational_state.get(sender, 'start')

    # 1. TRIGGER LOGIN ADMIN
    if msg_lower == "/admin":
        conversational_state[sender] = 'admin_auth'
        msg.body("🔐 *BOLICHE OS v5*\nIngresá contraseña:")
        return Response(content=str(resp), media_type="application/xml")

    # 2. LOGIN ADMIN
    if state == 'admin_auth':
        if incoming_msg == ADMIN_PASSWORD:
            conversational_state[sender] = 'admin_menu'
            msg.body("✅ *Acceso Admin*\n\n1. 📊 Dashboard\n2. 📢 Difusión\n3. 🎫 Alta VIP Manual\n4. 🚪 Salir")
        else:
            conversational_state[sender] = 'start'
            msg.body("❌ Clave incorrecta.")
        return Response(content=str(resp), media_type="application/xml")

    # 3. MENÚ ADMIN
    if state == 'admin_menu':
        if msg_lower == '1': # Dashboard
            total = db.query(func.count(Reserva.id)).scalar()
            msg.body(f"📊 *Stats*\nTickets: {total}\n(Enviá 0 para actualizar)")
            # Nos quedamos en el menú
        
        elif msg_lower == '2': # Broadcast
            conversational_state[sender] = 'admin_broadcast'
            msg.body("📢 Escribí el mensaje para todos:")
        
        elif msg_lower == '3': # Alta Manual
            conversational_state[sender] = 'admin_manual'
            msg.body("🎫 *Alta Manual*\n\nEscribí: Nombre, Cantidad\nEj: _Messi, 10_")
        
        elif msg_lower == '4': # Salir
            conversational_state[sender] = 'start'
            msg.body("👋 Sesión cerrada.")
        
        elif msg_lower == '0':
            msg.body("🔙 Menú Principal")

        else:
            msg.body("Opción no válida. 1, 2, 3 o 4.")
        
        return Response(content=str(resp), media_type="application/xml")

    # 4. HERRAMIENTAS ADMIN
    if state == 'admin_broadcast':
        # Simulamos envío y volvemos al menú
        cant = db.query(Reserva.id).count()
        msg.body(f"🚀 *Enviado a {cant} usuarios:*\n\n_{incoming_msg}_")
        conversational_state[sender] = 'admin_menu'
        return Response(content=str(resp), media_type="application/xml")

    if state == 'admin_manual':
        if "," not in incoming_msg:
            msg.body("⚠️ Falta la coma.\nEscribí: Nombre, Cantidad")
            return Response(content=str(resp), media_type="application/xml")
        
        try:
            datos = incoming_msg.split(',')
            nombre = datos[0].strip().title()
            cant = int(datos[1].strip())
            
            nueva = Reserva(whatsapp_id=sender, nombre_completo=nombre+" (VIP)", tipo_entrada="Mesa VIP", cantidad=cant, confirmada=True, rrpp_asignado="Admin")
            db.add(nueva)
            db.commit()
            
            # QR
            url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=VALIDO-{nueva.id}"
            msg.body(f"✅ Agregado: {nombre}")
            msg.media(url)
            
            # Creamos un SEGUNDO mensaje para preguntar si quiere otro
            # Esto evita que se quede trabado
            resp.message("¿Otro? Escribí 'Nombre, Cantidad' o 'MENU' para volver.")
            
        except:
            msg.body("⚠️ Error en los datos. Intentá de nuevo.")
        
        return Response(content=str(resp), media_type="application/xml")


    # --- CLIENTE NORMAL ---
    if state == 'start':
        if "cumple" in msg_lower:
            msg.body("🎂 ¡Feliz Cumple! Escribí 1 para tu regalo.")
            return Response(content=str(resp), media_type="application/xml")

        # Menu Cliente
        msg.body("👋 *Bienvenido a MOSCU*\n\n1. 🎫 Entrada General\n2. 🍾 Mesa VIP\n3. 🙋 Ayuda")
        conversational_state[sender] = 'choosing'
        return Response(content=str(resp), media_type="application/xml")

    if state == 'choosing':
        if msg_lower == '1':
            temp_data[sender] = {'tipo': 'General'}
            msg.body("🎫 ¿Cuántas entradas?")
            conversational_state[sender] = 'cant_gen'
        elif msg_lower == '2':
            temp_data[sender] = {'tipo': 'VIP'}
            msg.body("🍾 ¿A nombre de quién?")
            conversational_state[sender] = 'name_vip'
        elif msg_lower == '3':
            msg.body("📞 Hablá con Matias: wa.me/5491112345678")
            conversational_state[sender] = 'start'
        else:
            msg.body("Elegí 1, 2 o 3.")
        return Response(content=str(resp), media_type="application/xml")

    if state == 'cant_gen':
        if msg_lower.isdigit():
            cant = int(msg_lower)
            temp_data[sender]['cant'] = cant
            temp_data[sender]['names'] = []
            msg.body("Nombre de la persona 1:")
            conversational_state[sender] = 'names_gen'
        else:
            msg.body("Solo números.")
        return Response(content=str(resp), media_type="application/xml")

    if state == 'names_gen':
        data = temp_data[sender]
        data['names'].append(incoming_msg)
        
        if len(data['names']) < data['cant']:
            msg.body(f"Nombre persona {len(data['names'])+1}:")
        else:
            # Generar
            msg.body("⏳ Generando tickets...")
            rrpp = data.get('rrpp_origen', 'Organico')
            for n in data['names']:
                res = Reserva(whatsapp_id=sender, nombre_completo=n, tipo_entrada="General", cantidad=1, confirmada=True, rrpp_asignado=rrpp)
                db.add(res)
                db.commit()
                url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=ID-{res.id}"
                m = resp.message(f"✅ Ticket: {n}")
                m.media(url)
            conversational_state[sender] = 'start'
        return Response(content=str(resp), media_type="application/xml")

    if state == 'name_vip':
        temp_data[sender]['name'] = incoming_msg
        msg.body(f"Hola {incoming_msg}, ¿cuántas personas?")
        conversational_state[sender] = 'cant_vip'
        return Response(content=str(resp), media_type="application/xml")

    if state == 'cant_vip':
        if msg_lower.isdigit():
            cant = int(msg_lower)
            data = temp_data[sender]
            res = Reserva(whatsapp_id=sender, nombre_completo=data['name']+" (VIP)", tipo_entrada="Mesa VIP", cantidad=cant, confirmada=True)
            db.add(res)
            db.commit()
            msg.body(f"🥂 Lista Confirmada para {data['name']}.")
            conversational_state[sender] = 'start'
        else:
            msg.body("Solo números.")
        return Response(content=str(resp), media_type="application/xml")

    return Response(content=str(resp), media_type="application/xml")

# --- PANEL WEB SIMPLIFICADO ---
@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    filas = ""
    for r in reservas:
        filas += f"<tr><td>{r.id}</td><td>{r.nombre_completo}</td><td>{r.tipo_entrada}</td><td>{r.cantidad}</td><td>{r.rrpp_asignado}</td></tr>"
    return f"""
    <html><body>
    <h1>Panel MOSCU V5 (Clean)</h1>
    <table border="1">
    <tr><th>ID</th><th>Nombre</th><th>Tipo</th><th>Pax</th><th>RRPP</th></tr>
    {filas}
    </table></body></html>
    """