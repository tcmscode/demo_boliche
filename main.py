from fastapi import FastAPI, Form, Depends, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import func
from twilio.twiml.messaging_response import MessagingResponse
import datetime
import os
import sys
import traceback 

# --- 1. BASE DE DATOS BLINDADA ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://usuario:password@localhost/dbname")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Reconexión automática activada
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Reserva(Base):
    __tablename__ = "reservas_v9_platinum" # Tabla final
    
    id = Column(Integer, primary_key=True, index=True)
    whatsapp_id = Column(String, index=True)
    nombre_completo = Column(String)
    tipo_entrada = Column(String) 
    cantidad = Column(Integer)
    confirmada = Column(Boolean, default=False)
    fecha_reserva = Column(DateTime, default=datetime.datetime.utcnow)
    rrpp_asignado = Column(String, default="Organico")

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()

# --- 2. CONFIGURACIÓN DEL NEGOCIO ---
DIRECTORIO_RRPP = {
    "matias": {"nombre": "Matias (RRPP)", "celular": "5491111111111"},
    "sofia":  {"nombre": "Sofia (RRPP)", "celular": "5491122222222"},
    "general": {"nombre": "Soporte General", "celular": "5491133333333"}
}

ADMIN_PASSWORD = "Moscu123"
CUPO_TOTAL = 150
# URL de imagen estable (Servidor de demostración)
URL_FLYER = "https://images.unsplash.com/photo-1566737236500-c8ac43014a67?ixlib=rb-4.0.3&auto=format&fit=crop&w=1740&q=80"

# Memoria RAM del Bot
conversational_state = {}
temp_data = {}
user_attribution = {} 

# --- 3. CEREBRO DEL BOT ---
@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...), db: Session = Depends(get_db)):
    
    try:
        global conversational_state, temp_data, user_attribution
        
        sender = From
        incoming_msg = Body.strip()
        msg_lower = incoming_msg.lower()
        
        # Log para debug en Render
        print(f"📥 [V9] De: {sender} | Texto: {incoming_msg} | Estado: {conversational_state.get(sender, 'start')}")
        
        resp = MessagingResponse()
        msg = resp.message()

        # --- A. BOTÓN DE PÁNICO Y RESET ---
        palabras_escape = ["salir", "exit", "basta", "menu", "cancelar", "inicio"]
        if msg_lower in palabras_escape:
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            msg.body("🔄 *Menú Principal*")
            # Forzamos que caiga en la lógica de start abajo
            state = 'start' 
        
        elif msg_lower == "admin reset db":
            db.query(Reserva).delete()
            db.commit()
            conversational_state = {}
            msg.body("🗑️ *Sistema Reiniciado (V9)*\nBase de datos vacía. Listo para demo.")
            return Response(content=str(resp), media_type="application/xml")
        
        else:
            state = conversational_state.get(sender, 'start')

        # --- B. DETECCIÓN RRPP (Invisible) ---
        rrpp_detectado = "Organico"
        if "vengo de" in msg_lower:
            try:
                partes = msg_lower.split("vengo de ")
                if len(partes) > 1:
                    posible = partes[1].strip().split(" ")[0]
                    if posible in DIRECTORIO_RRPP:
                        user_attribution[sender] = posible
                        rrpp_detectado = posible
                        temp_data[sender] = {'rrpp_origen': posible}
            except: pass
        
        if sender in user_attribution:
            rrpp_detectado = user_attribution[sender]

        # --- C. MÁQUINA DE ESTADOS ---

        # >>> ZONA ADMIN <<<
        if msg_lower == "/admin":
            conversational_state[sender] = 'admin_auth'
            msg.body("🔐 *BOLICHE OS*\nIngresá contraseña:")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_auth':
            if incoming_msg == ADMIN_PASSWORD:
                conversational_state[sender] = 'admin_menu'
                msg.body("✅ *Acceso Admin*\n\n1. 📊 Dashboard\n2. 📢 Difusión\n3. 🎫 Alta VIP Manual\n4. 🚪 Salir")
            else:
                conversational_state[sender] = 'start'
                msg.body("❌ Contraseña incorrecta.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_menu':
            if msg_lower == '1': # Dashboard
                total = db.query(func.count(Reserva.id)).scalar()
                vip_c = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada == 'Mesa VIP').scalar()
                msg.body(f"📊 *Dashboard*\n\nTickets: {total}\nVIPs: {vip_c}\n\n(0 para actualizar)")
            elif msg_lower == '2': # Broadcast
                conversational_state[sender] = 'admin_broadcast'
                msg.body("📢 Escribí el mensaje de difusión:")
            elif msg_lower == '3': # Manual
                conversational_state[sender] = 'admin_manual'
                msg.body("🎫 *Alta Manual*\nFormato: Nombre, Cantidad")
            elif msg_lower == '4': 
                conversational_state[sender] = 'start'
                msg.body("🔒 Sesión cerrada.")
            elif msg_lower == '0':
                msg.body("🔙 Menú")
            else:
                msg.body("Opción inválida.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_broadcast':
            count = db.query(Reserva.id).count()
            msg.body(f"🚀 Enviado a {count} contactos.\n\nVolviendo al menú...")
            conversational_state[sender] = 'admin_menu'
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_manual':
            if "," not in incoming_msg:
                msg.body("⚠️ Falta la coma. Ej: Messi, 10")
            else:
                try:
                    d = incoming_msg.split(',')
                    nom = d[0].strip().title()
                    cant = int(d[1].strip())
                    new_res = Reserva(whatsapp_id=sender, nombre_completo=nom+" (VIP)", tipo_entrada="Mesa VIP", cantidad=cant, confirmada=True, rrpp_asignado="Admin")
                    db.add(new_res)
                    db.commit()
                    # QR
                    url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=https://bot-boliche-demo.onrender.com/check/{new_res.id}"
                    msg.body(f"✅ *Alta Exitosa*\nCliente: {nom}")
                    msg.media(url_qr)
                    resp.message("¿Otro? Escribí 'Nombre, Cantidad' o 'MENU'.")
                except:
                    msg.body("⚠️ Error en datos. Intenta de nuevo.")
            return Response(content=str(resp), media_type="application/xml")

        # >>> ZONA CLIENTE (FLOW PRINCIPAL) <<<
        if state == 'start':
            # Lógica FOMO
            total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
            
            if "cumple" in msg_lower:
                msg.body("🎂 ¡Feliz Cumple! Escribí 1 para activar tu beneficio.")
                return Response(content=str(resp), media_type="application/xml")

            if total_pax >= CUPO_TOTAL:
                 msg.body("⛔ *SOLD OUT* ⛔\nNo quedan más ingresos por hoy.")
            else:
                # Texto dinámico según cupo
                aviso = ""
                if total_pax > (CUPO_TOTAL - 20):
                    aviso = "🔥 *¡ÚLTIMOS LUGARES!* 🔥\n"
                
                # Saludo personalizado
                saludo = f"{aviso}¡Hola! Bienvenid@ a *MOSCU*.\n"
                if sender in temp_data and 'rrpp_origen' in temp_data[sender]:
                    rrpp_name = DIRECTORIO_RRPP[temp_data[sender]['rrpp_origen']]['nombre']
                    saludo = f"👋 ¡Te envía *{rrpp_name}*!\n{aviso}"

                msg.body(f"{saludo}\n1. 🎫 Entrada General\n2. 🍾 Mesa VIP\n3. 🙋 Ayuda / RRPP")
                msg.media(URL_FLYER)
                conversational_state[sender] = 'choosing'
            return Response(content=str(resp), media_type="application/xml")

        if state == 'choosing':
            if msg_lower == '1':
                temp_data[sender] = {'tipo': 'General', 'names': []}
                msg.body("🎫 *General*: ¿Cuántas entradas necesitás?")
                conversational_state[sender] = 'cant_gen'
            elif msg_lower == '2':
                temp_data[sender] = {'tipo': 'VIP'}
                msg.body("🍾 *Mesa VIP*: ¿A nombre de quién?")
                conversational_state[sender] = 'name_vip'
            elif msg_lower == '3':
                rrpp = user_attribution.get(sender, 'general')
                cel = DIRECTORIO_RRPP.get(rrpp, DIRECTORIO_RRPP['general'])['celular']
                msg.body(f"📞 Contacto directo:\n👉 https://wa.me/{cel}")
                conversational_state[sender] = 'start'
            else:
                msg.body("Por favor, respondé 1, 2 o 3.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'cant_gen':
            if msg_lower.isdigit():
                c = int(msg_lower)
                if c > 0:
                    temp_data[sender]['total'] = c
                    msg.body("Escribí el *Nombre y Apellido* de la persona 1:")
                    conversational_state[sender] = 'names_gen'
                else: msg.body("El número debe ser mayor a 0.")
            else: msg.body("Enviá solo el número (ej: 2).")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'names_gen':
            dat = temp_data[sender]
            dat['names'].append(incoming_msg.title())
            
            if len(dat['names']) < dat['total']:
                msg.body(f"Nombre de la persona {len(dat['names'])+1}:")
            else:
                msg.body("⏳ Procesando tickets...")
                rrpp = dat.get('rrpp_origen', rrpp_detectado)
                
                for n in dat['names']:
                    r = Reserva(whatsapp_id=sender, nombre_completo=n, tipo_entrada="General", cantidad=1, confirmada=True, rrpp_asignado=rrpp)
                    db.add(r)
                    db.commit()
                    
                    # URL Scanner
                    url_val = f"https://bot-boliche-demo.onrender.com/check/{r.id}"
                    url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={url_val}"
                    
                    m = resp.message(f"✅ Ticket: {n}")
                    m.media(url_qr)
                
                conversational_state[sender] = 'start'
            return Response(content=str(resp), media_type="application/xml")

        if state == 'name_vip':
            temp_data[sender]['name'] = incoming_msg
            msg.body(f"Perfecto {incoming_msg}, ¿cuántas personas son?")
            conversational_state[sender] = 'cant_vip'
            return Response(content=str(resp), media_type="application/xml")

        if state == 'cant_vip':
            if msg_lower.isdigit():
                c = int(msg_lower)
                dat = temp_data[sender]
                rrpp = dat.get('rrpp_origen', rrpp_detectado)
                
                r = Reserva(whatsapp_id=sender, nombre_completo=dat['name']+" (VIP)", tipo_entrada="Mesa VIP", cantidad=c, confirmada=True, rrpp_asignado=rrpp)
                db.add(r)
                db.commit()
                
                msg.body(f"🥂 *Mesa Confirmada*\nTitular: {dat['name']}\nPax: {c}\n\nPresentate en puerta VIP.")
                conversational_state[sender] = 'start'
            else: msg.body("Solo números.")
            return Response(content=str(resp), media_type="application/xml")

        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        print(f"⚠️ ERROR: {traceback.format_exc()}")
        conversational_state[sender] = 'start'
        resp = MessagingResponse()
        resp.message("⚠️ Error de conexión. Escribí 'Hola' para reiniciar.")
        return Response(content=str(resp), media_type="application/xml")

# --- 4. WEB ENDPOINTS (PANEL) ---
@app.get("/check/{ticket_id}", response_class=HTMLResponse)
def validar_ticket(ticket_id: int, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == ticket_id).first()
    if not reserva:
        return "<h1 style='color:red;font-size:4em;text-align:center;margin-top:20%'>❌ INVALIDO</h1>"
    return f"<div style='background:green;color:white;text-align:center;padding:50px'><h1>✅ VALIDO</h1><h2>{reserva.nombre_completo}</h2><p>{reserva.tipo_entrada}</p></div>"

@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    # Stats
    total = db.query(func.count(Reserva.id)).scalar() or 0
    vip = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada == 'Mesa VIP').scalar() or 0
    gral = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada == 'General').scalar() or 0
    
    filas = ""
    for r in reservas:
        filas += f"<tr><td>{r.id}</td><td>{r.fecha_reserva.strftime('%H:%M')}</td><td>{r.nombre_completo}</td><td>{r.tipo_entrada}</td><td>{r.cantidad}</td><td>{r.rrpp_asignado}</td></tr>"

    return f"""
    <html><head><title>MOSCU V9</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>body{{font-family:sans-serif;padding:20px;background:#f4f4f4}} table{{width:100%;background:white;border-collapse:collapse}} th,td{{padding:10px;border:1px solid #ddd}} .box{{max-width:800px;margin:0 auto}}</style>
    </head><body><div class="box">
    <h1>🦁 Panel MOSCU</h1>
    <div style="width:300px;margin:20px auto"><canvas id="c"></canvas></div>
    <table><tr><th>ID</th><th>Hora</th><th>Nombre</th><th>Tipo</th><th>Pax</th><th>RRPP</th></tr>{filas}</table>
    </div><script>new Chart(document.getElementById('c'),{{type:'doughnut',data:{{labels:['Gral','VIP'],datasets:[{{data:[{gral},{vip}],backgroundColor:['#36A2EB','#FF6384']}}]}}}})</script></body></html>
    """