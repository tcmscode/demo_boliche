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

# --- 1. BASE DE DATOS ROBUSTA ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://usuario:password@localhost/dbname")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Reserva(Base):
    __tablename__ = "reservas_v13_night" # Tabla V13
    
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

# --- 2. CONFIGURACIÓN ---
DIRECTORIO_RRPP = {
    "matias": {"nombre": "Matias (RRPP)", "celular": "5491111111111"},
    "sofia":  {"nombre": "Sofia (RRPP)", "celular": "5491122222222"},
    "general": {"nombre": "Soporte General", "celular": "5491133333333"}
}

ADMIN_PASSWORD = "Moscu123"
CUPO_TOTAL = 150
URL_FLYER = "https://i.ibb.co/mFG17TST/Imagen-Bohemian-Demo.jpg"

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
        
        print(f"📥 [MSG] {sender}: {incoming_msg} | Estado: {conversational_state.get(sender, 'start')}")
        
        resp = MessagingResponse()
        msg = resp.message()

        # --- A. NAVEGACIÓN ---
        palabras_escape = ["menu", "cancelar", "inicio", "basta"]
        palabras_salida = ["salir", "exit"]
        current_state = conversational_state.get(sender, 'start')

        if msg_lower in palabras_salida:
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            msg.body("🔒 *Sesión Reiniciada*")
            state = 'start'

        elif msg_lower in palabras_escape:
            if current_state.startswith('admin_'):
                conversational_state[sender] = 'admin_menu'
                msg.body("🔙 *Menú Admin*\n\n1. 📊 Dashboard\n2. 📢 Difusión\n3. 🎫 Alta Manual\n4. 🚪 Salir")
                return Response(content=str(resp), media_type="application/xml")
            else:
                conversational_state[sender] = 'start'
                temp_data[sender] = {}
                state = 'start'
        
        elif msg_lower == "admin reset db":
            db.query(Reserva).delete()
            db.commit()
            conversational_state = {}
            msg.body("🗑️ *Base de Datos V13 Limpia*")
            return Response(content=str(resp), media_type="application/xml")
        
        else:
            state = conversational_state.get(sender, 'start')

        # --- B. DETECCIÓN RRPP ---
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
        if sender in user_attribution: rrpp_detectado = user_attribution[sender]

        # --- C. ADMIN FLOW ---
        if msg_lower == "/admin":
            conversational_state[sender] = 'admin_auth'
            msg.body("🔐 *BOLICHE OS*\nContraseña:")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_auth':
            if incoming_msg == ADMIN_PASSWORD:
                conversational_state[sender] = 'admin_menu'
                msg.body("✅ *Acceso Admin*\n\n1. 📊 Dashboard\n2. 📢 Difusión\n3. 🎫 Alta Manual (Gral/VIP)\n4. 🚪 Salir")
            else:
                conversational_state[sender] = 'start'
                msg.body("❌ Incorrecto.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_menu':
            if msg_lower == '1': 
                total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
                msg.body(f"📊 *Dashboard Real*\n\n👥 Pax: {total_pax}/{CUPO_TOTAL}\n(Escribí 'menu' para volver)")
            elif msg_lower == '2': 
                conversational_state[sender] = 'admin_broadcast'
                msg.body("📢 Escribí el mensaje de difusión:")
            elif msg_lower == '3': 
                conversational_state[sender] = 'admin_manual_select'
                msg.body("🎫 *Tipo de Alta:*\n1. 🎟️ General (QR)\n2. 🥂 Mesa VIP (Lista)")
            elif msg_lower == '4': 
                conversational_state[sender] = 'start'
                msg.body("🔒 Saliste.")
            elif msg_lower == '0' or msg_lower == 'menu':
                msg.body("🔙 *Menú Admin*")
            else: msg.body("Opción inválida.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_manual_select':
            if msg_lower == '1':
                conversational_state[sender] = 'admin_manual_general'
                msg.body("🎟️ *Alta General*\nFormat: Nombre, Cantidad")
            elif msg_lower == '2':
                conversational_state[sender] = 'admin_manual_vip'
                msg.body("🥂 *Alta Mesa VIP*\nFormat: Nombre, Cantidad")
            else: msg.body("1 o 2.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_manual_general':
            if "," not in incoming_msg: msg.body("⚠️ Falta coma. Ej: Juan, 2")
            else:
                try:
                    d = incoming_msg.split(',')
                    nom = d[0].strip().title()
                    cant = int(d[1].strip())
                    new_res = Reserva(whatsapp_id=sender, nombre_completo=nom+" (MANUAL)", tipo_entrada="General", cantidad=cant, confirmada=True, rrpp_asignado="Admin")
                    db.add(new_res)
                    db.commit()
                    url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=https://bot-boliche-demo.onrender.com/check/{new_res.id}"
                    msg.body(f"✅ *Alta Gral OK*\n{nom} ({cant} pax)")
                    msg.media(url_qr)
                    resp.message("¿Otro? 'Nombre, Cantidad' o 'MENU'.")
                except: msg.body("⚠️ Error datos.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_manual_vip':
            if "," not in incoming_msg: msg.body("⚠️ Falta coma. Ej: Messi, 10")
            else:
                try:
                    d = incoming_msg.split(',')
                    nom = d[0].strip().title()
                    cant = int(d[1].strip())
                    new_res = Reserva(whatsapp_id=sender, nombre_completo=nom+" (MANUAL VIP)", tipo_entrada="Mesa VIP", cantidad=cant, confirmada=True, rrpp_asignado="Admin")
                    db.add(new_res)
                    db.commit()
                    msg.body(f"✅ *Mesa OK*\n{nom} ({cant} pax)\n_Sin QR_")
                    resp.message("¿Otra? 'Nombre, Cantidad' o 'MENU'.")
                except: msg.body("⚠️ Error datos.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_broadcast':
            count = db.query(Reserva.id).count()
            msg.body(f"🚀 Enviado a {count} pax (Simulado).")
            conversational_state[sender] = 'admin_menu'
            resp.message("🔙 *Menú Admin*")
            return Response(content=str(resp), media_type="application/xml")

        # >>> CLIENTE FLOW <<<
        if state == 'start':
            if "cumple" in msg_lower:
                msg.body("🎂 ¡Regalo Activo! Escribí 1.")
                return Response(content=str(resp), media_type="application/xml")
            
            total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
            if total_pax >= CUPO_TOTAL:
                 msg.body("⛔ *SOLD OUT*")
            else:
                aviso = ""
                if total_pax > (CUPO_TOTAL - 20): aviso = "🔥 *¡ÚLTIMOS LUGARES!* 🔥\n"
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
                msg.body("🎫 *General*: ¿Cuántas entradas?")
                conversational_state[sender] = 'cant_gen'
            elif msg_lower == '2':
                temp_data[sender] = {'tipo': 'VIP'}
                msg.body("🍾 *Mesa VIP*: ¿A nombre de quién?")
                conversational_state[sender] = 'name_vip'
            
            elif msg_lower == '3':
                # --- FIX OPCION 3 ---
                # Recuperamos RRPP de forma segura
                rrpp_key = user_attribution.get(sender, 'general')
                if rrpp_key not in DIRECTORIO_RRPP: rrpp_key = 'general'
                
                info = DIRECTORIO_RRPP[rrpp_key]
                link = f"https://wa.me/{info['celular']}?text=Hola,%20necesito%20ayuda"
                
                msg.body(f"📞 *Contacto RRPP ({info['nombre']})*\n\nHacé clic acá:\n👉 {link}")
                # Reiniciamos estado para que al escribir "Hola" empiece de nuevo
                conversational_state[sender] = 'start'
            
            else: msg.body("Opción inválida (1, 2 o 3).")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'cant_gen':
            if msg_lower.isdigit():
                c = int(msg_lower)
                if c > 0:
                    temp_data[sender]['total'] = c
                    msg.body("Nombre persona 1:")
                    conversational_state[sender] = 'names_gen'
                else: msg.body("Mayor a 0.")
            else: msg.body("Solo números.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'names_gen':
            dat = temp_data[sender]
            dat['names'].append(incoming_msg.title())
            if len(dat['names']) < dat['total']:
                msg.body(f"Nombre persona {len(dat['names'])+1}:")
            else:
                msg.body("⏳ Procesando...")
                rrpp = dat.get('rrpp_origen', rrpp_detectado)
                for n in dat['names']:
                    r = Reserva(whatsapp_id=sender, nombre_completo=n, tipo_entrada="General", cantidad=1, confirmada=True, rrpp_asignado=rrpp)
                    db.add(r)
                    db.commit()
                    url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=https://bot-boliche-demo.onrender.com/check/{r.id}"
                    m = resp.message(f"✅ Ticket: {n}")
                    m.media(url_qr)
                conversational_state[sender] = 'start'
            return Response(content=str(resp), media_type="application/xml")

        if state == 'name_vip':
            temp_data[sender]['name'] = incoming_msg
            msg.body(f"Hola {incoming_msg}, ¿cantidad de gente?")
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
                msg.body(f"🥂 *Confirmado*: {dat['name']} ({c} pax)")
                conversational_state[sender] = 'start'
            else: msg.body("Solo números.")
            return Response(content=str(resp), media_type="application/xml")

        return Response(content=str(resp), media_type="application/xml")

    except Exception as e:
        print(f"ERROR: {traceback.format_exc()}")
        conversational_state[sender] = 'start'
        resp = MessagingResponse()
        resp.message("⚠️ Error interno.")
        return Response(content=str(resp), media_type="application/xml")

# --- 4. PANEL WEB DARK MODE ---
@app.get("/check/{ticket_id}", response_class=HTMLResponse)
def validar_ticket(ticket_id: int, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == ticket_id).first()
    if not reserva:
        return "<body style='background:black;display:flex;justify-content:center;align-items:center;height:100vh'><h1 style='color:red;font-size:4em;font-family:sans-serif'>❌ INVALIDO</h1></body>"
    return f"""
    <body style='background:black;color:white;font-family:sans-serif;display:flex;flex-direction:column;justify-content:center;align-items:center;height:100vh'>
        <div style='font-size:100px'>✅</div>
        <h1 style='color:#00ff9d;font-size:3em;margin:0'>ACCESO OK</h1>
        <h2 style='font-size:2.5em;margin:20px 0'>{reserva.nombre_completo}</h2>
        <div style='background:#333;padding:10px 40px;border-radius:50px;font-size:1.5em;color:#ff00ff;border:2px solid #ff00ff'>{reserva.tipo_entrada}</div>
    </body>
    """

@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    
    # PAX Reales (Suma)
    total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
    total_vip = db.query(func.sum(Reserva.cantidad)).filter(Reserva.tipo_entrada == 'Mesa VIP').scalar() or 0
    total_gral = db.query(func.sum(Reserva.cantidad)).filter(Reserva.tipo_entrada == 'General').scalar() or 0
    
    filas = ""
    for r in reservas:
        color = '#ff00ff' if 'VIP' in r.tipo_entrada else '#00ff9d'
        filas += f"""<tr style='border-bottom:1px solid #222'>
            <td style='padding:15px'>#{r.id}</td>
            <td>{r.fecha_reserva.strftime('%H:%M')}</td>
            <td style='font-weight:bold;font-size:1.1em'>{r.nombre_completo}</td>
            <td style='color:{color}'>{r.tipo_entrada}</td>
            <td style='text-align:center;font-weight:bold'>{r.cantidad}</td>
            <td style='color:#888'>{r.rrpp_asignado}</td></tr>"""
    
    return f"""
    <html>
    <head>
        <title>MOSCU Night</title>
        <meta http-equiv="refresh" content="10">
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700&display=swap" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
            function exportCSV() {{
                var csv = [];
                var rows = document.querySelectorAll("table tr");
                for (var i = 0; i < rows.length; i++) {{
                    var row = [], cols = rows[i].querySelectorAll("td, th");
                    for (var j = 0; j < cols.length; j++) 
                        row.push('"' + cols[j].innerText + '"'); 
                    csv.push(row.join(","));        
                }}
                var blob = new Blob(["\\uFEFF" + csv.join("\\n")], {{ type: 'text/csv; charset=utf-8;' }});
                var link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                link.download = "Moscu_List_" + new Date().toISOString().slice(0,10) + ".csv";
                link.click();
            }}
        </script>
        <style>
            body {{ background-color: #050505; color: #fff; font-family: 'Montserrat', sans-serif; padding: 40px; }}
            .card {{ background: #111; padding: 20px; border-radius: 15px; border: 1px solid #333; text-align: center; }}
            h1 {{ background: -webkit-linear-gradient(#00ff9d, #00b8ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
            .btn {{ background: #00ff9d; color: black; padding: 10px 20px; border: none; font-weight: bold; cursor: pointer; border-radius: 5px; }}
        </style>
    </head>
    <body>
        <div style="max-width:1200px;margin:0 auto">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:30px">
                <h1>🦁 MOSCU NIGHT MANAGER</h1>
                <button class="btn" onclick="exportCSV()">BAJAR EXCEL</button>
            </div>
            
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-bottom:40px">
                <div class="card"><h3>PAX TOTAL</h3><h2 style="font-size:3em;margin:0">{total_pax}</h2></div>
                <div class="card" style="border-color:#ff00ff"><h3>VIP</h3><h2 style="color:#ff00ff;font-size:3em;margin:0">{total_vip}</h2></div>
                <div class="card" style="border-color:#00ff9d"><h3>GENERAL</h3><h2 style="color:#00ff9d;font-size:3em;margin:0">{total_gral}</h2></div>
            </div>

            <table style="width:100%;border-collapse:collapse">
                <tr style="text-align:left;color:#666"><th>ID</th><th>HORA</th><th>NOMBRE</th><th>TIPO</th><th>PAX</th><th>RRPP</th></tr>
                {filas}
            </table>
        </div>
    </body>
    </html>
    """