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

# --- 1. CONFIGURACIÓN DE BASE DE DATOS OPTIMIZADA ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://usuario:password@localhost/dbname")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# pool_pre_ping=True: Mantiene la conexión viva y evita desconexiones de Render
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Reserva(Base):
    __tablename__ = "reservas_v8_gold" # Tabla final limpia
    
    id = Column(Integer, primary_key=True, index=True)
    whatsapp_id = Column(String, index=True)
    nombre_completo = Column(String)
    tipo_entrada = Column(String) 
    cantidad = Column(Integer)
    confirmada = Column(Boolean, default=False)
    fecha_reserva = Column(DateTime, default=datetime.datetime.utcnow)
    rrpp_asignado = Column(String, default="Organico")

# Crear tablas automáticamente
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

# Variables Globales (Memoria RAM)
conversational_state = {}
temp_data = {}
user_attribution = {} 

# --- 3. CEREBRO DEL BOT (CORE BLINDADO) ---
@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...), db: Session = Depends(get_db)):
    
    # Bloque TRY/EXCEPT GLOBAL: Si algo falla, el bot NO muere.
    try:
        global conversational_state, temp_data, user_attribution
        
        sender = From
        incoming_msg = Body.strip()
        msg_lower = incoming_msg.lower()
        
        # Log en consola de Render para monitoreo (Vital para debug)
        print(f"📥 [MSG] De: {sender} | Texto: {incoming_msg} | Estado: {conversational_state.get(sender, 'start')}")
        
        resp = MessagingResponse()
        msg = resp.message()

        # --- A. BOTÓN DE PÁNICO (Funciona SIEMPRE) ---
        palabras_escape = ["salir", "exit", "basta", "menu", "cancelar", "inicio", "reset"]
        if msg_lower in palabras_escape:
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            msg.body("🔄 *SISTEMA REINICIADO*\nVolviste al menú principal.")
            return Response(content=str(resp), media_type="application/xml")

        # --- B. ADMIN RESET DB (Borrado Total) ---
        if msg_lower == "admin reset db":
            db.query(Reserva).delete()
            db.commit()
            conversational_state = {}
            temp_data = {}
            msg.body("🗑️ *FACTORY RESET V8*\nBase de datos limpia y memoria reiniciada.")
            return Response(content=str(resp), media_type="application/xml")

        # --- C. DETECCIÓN RRPP (Sticky Session) ---
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

        # --- D. MÁQUINA DE ESTADOS ---
        state = conversational_state.get(sender, 'start')

        # >>>>> ZONA ADMIN <<<<<
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
                msg.body(f"📊 *Dashboard*\nTickets Emitidos: {total}\n(Enviá 0 para actualizar)")
            elif msg_lower == '2': # Broadcast
                conversational_state[sender] = 'admin_broadcast'
                msg.body("📢 Escribí el mensaje de difusión (Simulacro):")
            elif msg_lower == '3': # Manual
                conversational_state[sender] = 'admin_manual'
                msg.body("🎫 *Alta Manual VIP*\n\nEscribí: Nombre, Cantidad\nEjemplo: _Messi, 10_")
            elif msg_lower == '4': 
                conversational_state[sender] = 'start'
                msg.body("🔒 Sesión cerrada.")
            elif msg_lower == '0':
                msg.body("🔙 Menú Principal")
            else:
                msg.body("Opción inválida (1-4).")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_broadcast':
            # Simulación de envío masivo
            count = db.query(Reserva.id).count()
            msg.body(f"🚀 *Simulación Completada*\nMensaje enviado a {count} usuarios.\n\nVolviendo al menú...")
            conversational_state[sender] = 'admin_menu'
            return Response(content=str(resp), media_type="application/xml")

        if state == 'admin_manual':
            # VALIDACIÓN ESTRICTA ANTI-CRASH
            if "," not in incoming_msg:
                msg.body("⚠️ *Error de Formato*\nFalta la coma (,).\nEscribí: *Nombre, Cantidad*")
            else:
                try:
                    d = incoming_msg.split(',')
                    nom = d[0].strip().title()
                    cant = int(d[1].strip())
                    
                    new_res = Reserva(whatsapp_id=sender, nombre_completo=nom+" (VIP)", tipo_entrada="Mesa VIP", cantidad=cant, confirmada=True, rrpp_asignado="Admin")
                    db.add(new_res)
                    db.commit()
                    
                    # Generación QR
                    url_val = f"https://bot-boliche-demo.onrender.com/check/{new_res.id}"
                    url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={url_val}"
                    
                    msg.body(f"✅ *Alta Exitosa*\nCliente: {nom}")
                    msg.media(url_qr)
                    resp.message("¿Cargar otro? Escribí 'Nombre, Cantidad' o 'MENU' para salir.")
                except ValueError:
                    msg.body("⚠️ La cantidad debe ser un número entero.")
                except Exception as e:
                    msg.body(f"⚠️ Error desconocido: {str(e)}")
            return Response(content=str(resp), media_type="application/xml")

        # >>>>> ZONA CLIENTE <<<<<
        if state == 'start':
            if "cumple" in msg_lower:
                msg.body("🎂 ¡Feliz Cumple! Escribí 1 para tu beneficio.")
                return Response(content=str(resp), media_type="application/xml")
            
            total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
            if total_pax >= CUPO_TOTAL:
                 msg.body("⛔ *SOLD OUT* ⛔\nCapacidad máxima alcanzada.")
            else:
                # Flyer Link
                msg.body("👋 *Bienvenido a MOSCU*\n\n1. 🎫 Entrada General\n2. 🍾 Mesa VIP\n3. 🙋 Ayuda")
                msg.media("https://i.ibb.co/mFG17TST/Imagen-Bohemian-Demo.jpg")
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
                msg.body(f"📞 Contactá a tu RRPP aquí:\n👉 https://wa.me/{cel}")
                conversational_state[sender] = 'start'
            else:
                msg.body("Respondé 1, 2 o 3.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'cant_gen':
            if msg_lower.isdigit():
                c = int(msg_lower)
                if c > 0:
                    temp_data[sender]['total'] = c
                    msg.body("Nombre y Apellido de la persona 1:")
                    conversational_state[sender] = 'names_gen'
                else: msg.body("Ingresa un número mayor a 0.")
            else: msg.body("Por favor, enviá solo el número.")
            return Response(content=str(resp), media_type="application/xml")

        if state == 'names_gen':
            dat = temp_data[sender]
            dat['names'].append(incoming_msg.title())
            
            if len(dat['names']) < dat['total']:
                msg.body(f"Nombre de la persona {len(dat['names'])+1}:")
            else:
                # Generación de Tickets
                msg.body("⏳ Generando tickets...")
                rrpp = dat.get('rrpp_origen', rrpp_detectado)
                
                for n in dat['names']:
                    r = Reserva(whatsapp_id=sender, nombre_completo=n, tipo_entrada="General", cantidad=1, confirmada=True, rrpp_asignado=rrpp)
                    db.add(r)
                    db.commit()
                    
                    url_val = f"https://bot-boliche-demo.onrender.com/check/{r.id}"
                    url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={url_val}"
                    
                    m = resp.message(f"✅ Ticket: {n}")
                    m.media(url_qr)
                
                conversational_state[sender] = 'start'
            return Response(content=str(resp), media_type="application/xml")

        if state == 'name_vip':
            temp_data[sender]['name'] = incoming_msg
            msg.body(f"Hola {incoming_msg}, ¿cuántas personas son?")
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
        # RECUPERACIÓN DE ERRORES: El bot nunca muere.
        print(f"⚠️ ERROR CRÍTICO: {traceback.format_exc()}") # Log detallado en Render
        error_msg = f"⚠️ Ocurrió un error interno. El sistema se ha reiniciado."
        conversational_state[sender] = 'start'
        resp = MessagingResponse()
        resp.message(error_msg)
        return Response(content=str(resp), media_type="application/xml")

# --- 4. ENDPOINTS WEB (PANEL & SCANNER) ---

@app.get("/check/{ticket_id}", response_class=HTMLResponse)
def validar_ticket(ticket_id: int, db: Session = Depends(get_db)):
    reserva = db.query(Reserva).filter(Reserva.id == ticket_id).first()
    if not reserva:
        return """<html><body style="background:#e74c3c;color:white;text-align:center;font-family:sans-serif;padding-top:50px;">
        <h1 style="font-size:80px;">❌</h1><h1>TICKET INVÁLIDO</h1></body></html>"""
    
    return f"""<html><body style="background:#2ecc71;color:white;text-align:center;font-family:sans-serif;padding-top:50px;">
        <h1 style="font-size:80px;">✅</h1><h1>ACCESO PERMITIDO</h1>
        <h2>{reserva.nombre_completo}</h2><p>{reserva.tipo_entrada}</p>
        <p>RRPP: {reserva.rrpp_asignado}</p></body></html>"""

@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    
    total_gral = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada == 'General').scalar() or 0
    total_vip = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada == 'Mesa VIP').scalar() or 0
    
    filas = ""
    for r in reservas:
        color = '#2980b9' if r.tipo_entrada == 'General' else '#d35400'
        rrpp_style = 'color:#2ecc71;font-weight:bold' if r.rrpp_asignado != 'Organico' else 'color:#bdc3c7'
        filas += f"""<tr>
            <td>{r.id}</td><td>{r.fecha_reserva.strftime('%H:%M')}</td><td>{r.whatsapp_id}</td>
            <td style="font-weight:bold;color:#ecf0f1">{r.nombre_completo}</td>
            <td><span style="background:{color};padding:4px 8px;border-radius:4px">{r.tipo_entrada}</span></td>
            <td>{r.cantidad}</td><td style="{rrpp_style}">{r.rrpp_asignado}</td></tr>"""

    return f"""
    <html>
    <head>
        <title>MOSCU Admin V8</title>
        <meta http-equiv="refresh" content="10">
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
                var blob = new Blob(["\\uFEFF" + csv.join("\\n")], {{ type: 'text/csv; charset=utf-8;' }});
                var link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                link.download = "reservas_moscu.csv";
                link.click();
            }}
        </script>
        <style>
            body {{ background: #121212; color: #ecf0f1; font-family: sans-serif; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; background: #1e1e1e; padding: 20px; border-radius: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; border-bottom: 1px solid #333; }}
            th {{ background: #2c3e50; }}
            .chart-box {{ width: 300px; margin: 20px auto; }}
            button {{ background: #27ae60; color: white; padding: 10px; border: none; cursor: pointer; float: right; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <button onclick="exportCSV()">💾 EXPORTAR EXCEL</button>
            <h1>🦁 MOSCU Night Manager</h1>
            <div class="chart-box"><canvas id="myChart"></canvas></div>
            <table><thead><tr><th>ID</th><th>Hora</th><th>WhatsApp</th><th>Nombre</th><th>Tipo</th><th>Pax</th><th>RRPP</th></tr></thead><tbody>{filas}</tbody></table>
        </div>
        <script>
            new Chart(document.getElementById('myChart'), {{
                type: 'doughnut',
                data: {{ labels: ['General', 'VIP'], datasets: [{{ data: [{total_gral}, {total_vip}], backgroundColor: ['#3498db', '#e67e22'], borderWidth: 0 }}] }},
                options: {{ plugins: {{ legend: {{ labels: {{ color: 'white' }} }} }} }}
            }});
        </script>
    </body>
    </html>
    """