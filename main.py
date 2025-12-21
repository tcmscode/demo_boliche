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

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Reserva(Base):
    __tablename__ = "reservas_v12_night" # Tabla final V12
    
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

        # --- NAVEGACIÓN Y SEGURIDAD ---
        palabras_escape = ["menu", "cancelar", "inicio", "basta"]
        palabras_salida = ["salir", "exit"]
        
        current_state = conversational_state.get(sender, 'start')

        if msg_lower in palabras_salida:
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            msg.body("🔒 *Sesión Cerrada*")
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
            msg.body("🗑️ *Base de Datos V12 Limpia*")
            return Response(content=str(resp), media_type="application/xml")
        
        else:
            state = conversational_state.get(sender, 'start')

        # --- RRPP DETECTION ---
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

        # --- ADMIN FLOW ---
        if msg_lower == "/admin":
            conversational_state[sender] = 'admin_auth'
            msg.body("🔐 *BOLICHE OS*\nContraseña:")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_auth':
            if incoming_msg == ADMIN_PASSWORD:
                conversational_state[sender] = 'admin_menu'
                msg.body("✅ *Acceso Admin*\n\n1. 📊 Dashboard\n2. 📢 Difusión\n3. 🎫 Alta Manual\n4. 🚪 Salir")
            else:
                conversational_state[sender] = 'start'
                msg.body("❌ Incorrecto.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_menu':
            if msg_lower == '1': 
                # Cálculo de PAX REALES (Suma de cantidades)
                total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
                msg.body(f"📊 *Dashboard Real*\n\n👥 Pax Totales: {total_pax}/{CUPO_TOTAL}\n(Escribí 'menu' para volver)")
            elif msg_lower == '2': 
                conversational_state[sender] = 'admin_broadcast'
                msg.body("📢 Escribí el mensaje de difusión:")
            elif msg_lower == '3': 
                conversational_state[sender] = 'admin_manual_select'
                msg.body("🎫 *Seleccioná Tipo:*\n\n1. 🎟️ General (QR)\n2. 🥂 Mesa VIP (Lista)")
            elif msg_lower == '4': 
                conversational_state[sender] = 'start'
                msg.body("🔒 Saliste.")
            elif msg_lower == '0' or msg_lower == 'menu':
                msg.body("🔙 *Menú Admin*\n1. Dashboard\n2. Difusión\n3. Alta Manual\n4. Salir")
            else:
                msg.body("Opción inválida.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_manual_select':
            if msg_lower == '1':
                conversational_state[sender] = 'admin_manual_general'
                msg.body("🎟️ *Alta General*\nEscribí: Nombre, Cantidad")
            elif msg_lower == '2':
                conversational_state[sender] = 'admin_manual_vip'
                msg.body("🥂 *Alta Mesa VIP*\nEscribí: Nombre, Cantidad")
            else:
                msg.body("1 o 2.")
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
                    msg.body(f"✅ *Alta General*\n{nom} ({cant} pax)")
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
                    msg.body(f"✅ *Mesa Cargada*\n{nom} ({cant} pax)\n_Sin QR (Lista)_")
                    resp.message("¿Otra? 'Nombre, Cantidad' o 'MENU'.")
                except: msg.body("⚠️ Error datos.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_broadcast':
            count = db.query(Reserva.id).count()
            msg.body(f"🚀 Enviado a {count} pax (Simulado).")
            conversational_state[sender] = 'admin_menu'
            resp.message("🔙 *Menú Admin*")
            return Response(content=str(resp), media_type="application/xml")

        # >>> ZONA CLIENTE <<<
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
                rrpp = user_attribution.get(sender, 'general')
                cel = DIRECTORIO_RRPP.get(rrpp, DIRECTORIO_RRPP['general'])['celular']
                msg.body(f"📞 RRPP: https://wa.me/{cel}")
                conversational_state[sender] = 'start'
            else: msg.body("1, 2 o 3.")
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
        resp.message("⚠️ Error interno. Escribí 'Hola'.")
        return Response(content=str(resp), media_type="application/xml")

# --- 4. PANEL WEB (NIGHT MODE) ---
@app.get("/check/{ticket_id}", response_class=HTMLResponse)
def validar_ticket(ticket_id: int, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == ticket_id).first()
    if not reserva:
        return """
        <body style='background:black;color:white;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;flex-direction:column'>
            <div style='font-size:100px'>❌</div>
            <h1 style='color:red;font-size:3em;margin:0'>INVALIDO</h1>
        </body>
        """
    return f"""
    <body style='background:black;color:white;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;flex-direction:column'>
        <div style='font-size:100px'>✅</div>
        <h1 style='color:#0f0;font-size:3em;margin:0'>PERMITIDO</h1>
        <h2 style='font-size:2em;margin:20px 0'>{reserva.nombre_completo}</h2>
        <div style='background:#333;padding:10px 30px;border-radius:20px;font-size:1.5em'>{reserva.tipo_entrada}</div>
    </body>
    """

@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    
    # Cálculos reales de PAX (Suma de cantidades, no de filas)
    total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
    total_vip = db.query(func.sum(Reserva.cantidad)).filter(Reserva.tipo_entrada == 'Mesa VIP').scalar() or 0
    total_gral = db.query(func.sum(Reserva.cantidad)).filter(Reserva.tipo_entrada == 'General').scalar() or 0
    
    filas = ""
    for r in reservas:
        color_tipo = '#d946ef' if r.tipo_entrada == 'Mesa VIP' else '#22d3ee' # Pink vs Cyan
        filas += f"""
        <tr style='border-bottom:1px solid #333'>
            <td style='padding:15px'>#{r.id}</td>
            <td>{r.fecha_reserva.strftime('%H:%M')}</td>
            <td style='font-weight:bold'>{r.nombre_completo}</td>
            <td><span style='color:{color_tipo};border:1px solid {color_tipo};padding:2px 8px;border-radius:5px'>{r.tipo_entrada}</span></td>
            <td style='text-align:center;font-size:1.2em'>{r.cantidad}</td>
            <td style='color:#a3a3a3'>{r.rrpp_asignado}</td>
        </tr>"""
    
    return f"""
    <html>
    <head>
        <title>MOSCU Night Manager</title>
        <meta http-equiv="refresh" content="30">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
            function exportCSV() {{
                var csv = [];
                var rows = document.querySelectorAll("table tr");
                for (var i = 0; i < rows.length; i++) {{
                    var row = [], cols = rows[i].querySelectorAll("td, th");
                    for (var j = 0; j < cols.length; j++) {{
                        var data = cols[j].innerText.replace(/(\\r\\n|\\n|\\r)/gm, "").replace(/"/g, '""');
                        row.push('"' + data + '"');
                    }}
                    csv.push(row.join(","));        
                }}
                var now = new Date();
                var dateStr = now.toISOString().slice(0,10);
                var blob = new Blob(["\\uFEFF" + csv.join("\\n")], {{ type: 'text/csv; charset=utf-8;' }});
                var link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                link.download = "Moscu_Guestlist_" + dateStr + ".csv";
                link.click();
            }}
        </script>
        <style>
            body {{ background-color: #000; color: #fff; font-family: 'Inter', sans-serif; margin: 0; padding: 40px; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 40px; border-bottom: 2px solid #333; padding-bottom: 20px; }}
            h1 {{ margin: 0; font-size: 2.5em; letter-spacing: -1px; background: -webkit-linear-gradient(45deg, #d946ef, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
            .btn-export {{ background: #22c55e; color: black; padding: 12px 24px; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; transition: transform 0.2s; }}
            .btn-export:hover {{ transform: scale(1.05); background: #4ade80; }}
            
            .stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-bottom: 40px; }}
            .card {{ background: #111; border: 1px solid #333; padding: 20px; border-radius: 12px; text-align: center; }}
            .card h3 {{ margin: 0 0 10px 0; color: #888; font-size: 0.9em; text-transform: uppercase; }}
            .card .number {{ font-size: 3em; font-weight: bold; margin: 0; }}
            
            table {{ width: 100%; border-collapse: collapse; font-size: 0.95em; }}
            th {{ text-align: left; padding: 15px; color: #888; border-bottom: 2px solid #333; text-transform: uppercase; font-size: 0.8em; }}
            tr:hover {{ background: #111; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🦁 MOSCU NIGHT MANAGER</h1>
                <button class="btn-export" onclick="exportCSV()">⬇️ EXCEL DOWNLOAD</button>
            </div>
            
            <div class="stats-grid">
                <div class="card">
                    <h3>Total Pax</h3>
                    <p class="number" style="color: white">{total_pax}</p>
                </div>
                <div class="card" style="border-color: #d946ef33">
                    <h3>Mesa VIP Pax</h3>
                    <p class="number" style="color: #d946ef">{total_vip}</p>
                </div>
                <div class="card" style="border-color: #22d3ee33">
                    <h3>General Pax</h3>
                    <p class="number" style="color: #22d3ee">{total_gral}</p>
                </div>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>ID</th><th>Hora</th><th>Nombre Completo</th><th>Acceso</th><th>Pax</th><th>RRPP</th>
                    </tr>
                </thead>
                <tbody>
                    {filas}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """