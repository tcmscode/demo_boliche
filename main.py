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

# --- 1. CONFIGURACIÓN DE BASE DE DATOS ROBUSTA ---
# Usamos 'reservas_vfinal' para asegurar una tabla 100% limpia para la demo.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://usuario:password@localhost/dbname")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Reserva(Base):
    __tablename__ = "reservas_vfinal"
    
    id = Column(Integer, primary_key=True, index=True)
    whatsapp_id = Column(String, index=True)
    nombre_completo = Column(String)
    tipo_entrada = Column(String) 
    cantidad = Column(Integer)
    confirmada = Column(Boolean, default=False)
    fecha_reserva = Column(DateTime, default=datetime.datetime.utcnow)
    rrpp_asignado = Column(String, default="Organico")

# Crear tablas si no existen
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

# Variables Globales de Estado (Memoria RAM)
conversational_state = {}
temp_data = {}
user_attribution = {} 

# --- 3. EL CEREBRO DEL CHATBOT ---
@app.post("/webhook")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...), db: Session = Depends(get_db)):
    
    # Referencia a globales para poder resetearlas
    global conversational_state, temp_data, user_attribution
    
    sender = From
    incoming_msg = Body.strip()
    msg_lower = incoming_msg.lower()
    
    # LOGGING: Para ver en Render qué está pasando
    print(f"[LOG] Msg de {sender}: '{incoming_msg}' | Estado: {conversational_state.get(sender, 'start')}")
    
    resp = MessagingResponse()
    msg = resp.message()

    # ============================================================
    # 🛡️ CAPA DE SEGURIDAD 1: SALIDA DE EMERGENCIA (PRIORIDAD MÁXIMA)
    # ============================================================
    palabras_escape = ["salir", "exit", "basta", "menu", "cancelar", "inicio"]
    
    # Si el usuario quiere salir, rompemos cualquier flujo y reseteamos.
    if msg_lower in palabras_escape:
        conversational_state[sender] = 'start'
        temp_data[sender] = {}
        msg.body("🔄 *Reinicio*\nVolviste al menú principal.")
        return Response(content=str(resp), media_type="application/xml")

    # Comando Secreto: Hard Reset (Borra DB y Memoria)
    if msg_lower == "admin reset db":
        db.query(Reserva).delete()
        db.commit()
        conversational_state = {} 
        temp_data = {}
        msg.body("🗑️ *SISTEMA LIMPIO*\nBase de datos y memoria reiniciadas.")
        return Response(content=str(resp), media_type="application/xml")


    # ============================================================
    # 🕵️ CAPA DE LÓGICA: DETECCIÓN DE RRPP
    # ============================================================
    rrpp_detectado = "Organico"
    if "vengo de" in msg_lower:
        try:
            partes = msg_lower.split("vengo de ")
            if len(partes) > 1:
                posible_nombre = partes[1].strip().split(" ")[0]
                if posible_nombre in DIRECTORIO_RRPP:
                    user_attribution[sender] = posible_nombre
                    rrpp_detectado = posible_nombre
                    temp_data[sender] = {'rrpp_origen': posible_nombre}
        except:
            pass # Si falla el parsing, seguimos como organico
    
    if sender in user_attribution:
        rrpp_detectado = user_attribution[sender]


    # ============================================================
    # 🧠 CAPA DE ESTADOS (MÁQUINA DE DECISIONES)
    # ============================================================
    state = conversational_state.get(sender, 'start')

    # --- 🔒 FLUJO DE ADMINISTRADOR ---
    
    # Trigger de entrada
    if msg_lower == "/admin":
        conversational_state[sender] = 'admin_auth'
        msg.body("🔐 *BOLICHE OS*\nIngresá tu contraseña:")
        return Response(content=str(resp), media_type="application/xml")

    # Verificación de Password
    if state == 'admin_auth':
        if incoming_msg == ADMIN_PASSWORD:
            conversational_state[sender] = 'admin_menu'
            msg.body("✅ *Acceso Admin*\n\n1. 📊 Ver Dashboard\n2. 📢 Difusión Masiva\n3. 🎫 Alta VIP Manual\n4. 🚪 Cerrar Sesión")
        else:
            conversational_state[sender] = 'start'
            msg.body("❌ Contraseña incorrecta.")
        return Response(content=str(resp), media_type="application/xml")

    # Menú Principal Admin
    if state == 'admin_menu':
        if msg_lower == '1': # Dashboard
            total = db.query(func.count(Reserva.id)).scalar()
            vip_count = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada.contains("VIP")).scalar() or 0
            ocupacion = int((db.query(func.sum(Reserva.cantidad)).scalar() or 0) / CUPO_TOTAL * 100)
            
            msg.body(f"📊 *STATUS REPORT*\n\nTickets Totales: {total}\nVIPs: {vip_count}\nOcupación: {ocupacion}%\n\n_Escribí 0 para actualizar._")
            # Nos mantenemos en el menú
        
        elif msg_lower == '2': # Difusión
            conversational_state[sender] = 'admin_broadcast'
            msg.body("📢 *Modo Difusión*\nEscribí el mensaje para enviar a todos:")
        
        elif msg_lower == '3': # Alta Manual (Aquí estaba el problema)
            conversational_state[sender] = 'admin_manual'
            msg.body("🎫 *Alta Manual VIP*\n\nEscribí: *Nombre, Cantidad*\nEjemplo: _Messi, 10_\n\n(O escribí SALIR para volver)")
        
        elif msg_lower == '4': # Salir
            conversational_state[sender] = 'start'
            msg.body("🔒 Sesión cerrada.")
        
        elif msg_lower == '0':
            msg.body("🔙 Menú Principal.")
        
        else:
            msg.body("Opción no válida. Enviá 1, 2, 3 o 4.")
        
        return Response(content=str(resp), media_type="application/xml")

    # Ejecución de Herramientas Admin
    if state == 'admin_broadcast':
        # Simulamos el envío para no complicar la demo con APIs externas
        cant = db.query(Reserva.id).count()
        msg.body(f"🚀 *Enviado con éxito*\nTu mensaje llegó a {cant} usuarios.\n\nVolviendo al menú...")
        conversational_state[sender] = 'admin_menu'
        return Response(content=str(resp), media_type="application/xml")

    if state == 'admin_manual':
        # BLINDAJE ANTI-CRASH: Validamos formato antes de procesar
        if "," not in incoming_msg:
            msg.body("⚠️ *Error de Formato*\nFalta la coma.\n\nEscribí: *Nombre, Cantidad*\nEjemplo: _Ricky, 5_")
            return Response(content=str(resp), media_type="application/xml")
        
        try:
            # Intentamos procesar
            datos = incoming_msg.split(',')
            nombre_vip = datos[0].strip().title()
            cantidad_vip = int(datos[1].strip()) # Esto puede fallar si no es numero
            
            # Guardamos
            nueva = Reserva(
                whatsapp_id=sender, 
                nombre_completo=nombre_vip + " (VIP)", 
                tipo_entrada="Mesa VIP", 
                cantidad=cantidad_vip, 
                confirmada=True, 
                rrpp_asignado="Admin"
            )
            db.add(nueva)
            db.commit()
            
            # Generamos QR URL
            url_qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=VALIDO-VIP-{nueva.id}"
            
            msg.body(f"✅ *Alta Exitosa*\nCliente: {nombre_vip}\nPax: {cantidad_vip}")
            msg.media(url_qr)
            
            # Mensaje secundario para loop
            resp.message("¿Cargar otro? Enviá 'Nombre, Cantidad' o escribí MENU para salir.")
            
        except ValueError:
            msg.body("⚠️ La cantidad debe ser un número.\nEjemplo: _Ricky, 5_")
        except Exception as e:
            print(f"[ERROR] {e}") # Log interno
            msg.body("⚠️ Error desconocido. Intentá de nuevo.")
        
        return Response(content=str(resp), media_type="application/xml")


    # --- 👤 FLUJO DE CLIENTE (USUARIO NORMAL) ---

    if state == 'start':
        total_pax = db.query(func.sum(Reserva.cantidad)).scalar() or 0
        url_flyer = "https://i.ibb.co/mFG17TST/Imagen-Bohemian-Demo.jpg" 

        # Saludo personalizado si viene de RRPP
        saludo = ""
        if sender in temp_data and 'rrpp_origen' in temp_data[sender]:
            rrpp_name = DIRECTORIO_RRPP[temp_data[sender]['rrpp_origen']]['nombre']
            saludo = f"👋 ¡Te envía *{rrpp_name}*!\n"

        if total_pax >= CUPO_TOTAL:
             msg.body("⛔ *SOLD OUT* ⛔\nCapacidad máxima alcanzada.")
        else:
             msg.body(f"{saludo}¡Hola! Bienvenid@ a *MOSCU*.\n\n1. 🎫 Entrada General\n2. 🍾 Mesa VIP\n3. 🙋 Ayuda Humana")
             msg.media(url_flyer) 
             conversational_state[sender] = 'choosing'

    elif state == 'choosing':
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
            data_rrpp = DIRECTORIO_RRPP.get(rrpp, DIRECTORIO_RRPP['general'])
            link = f"https://wa.me/{data_rrpp['celular']}"
            msg.body(f"📞 Contactá a *{data_rrpp['nombre']}* aquí:\n👉 {link}")
            conversational_state[sender] = 'start'
        else:
            msg.body("Respondé 1, 2 o 3.")

    elif state == 'cant_gen':
        if msg_lower.isdigit():
            cant = int(msg_lower)
            if cant > 0:
                temp_data[sender]['total'] = cant
                msg.body(f"Son {cant} personas.\nNombre de la persona 1:")
                conversational_state[sender] = 'names_gen'
            else:
                msg.body("Debe ser mayor a 0.")
        else:
            msg.body("Solo números.")

    elif state == 'names_gen':
        data = temp_data[sender]
        data['names'].append(incoming_msg.title())
        
        if len(data['names']) < data['total']:
            msg.body(f"Nombre de la persona {len(data['names'])+1}:")
        else:
            # Procesar
            msg.body("⏳ Generando tickets...")
            rrpp_final = data.get('rrpp_origen', rrpp_detectado)
            
            for n in data['names']:
                res = Reserva(whatsapp_id=sender, nombre_completo=n, tipo_entrada="General", cantidad=1, confirmada=True, rrpp_asignado=rrpp_final)
                db.add(res)
                db.commit()
                url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=CHECK-{res.id}"
                m = resp.message(f"✅ Ticket: {n}")
                m.media(url)
            
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
            return Response(content=str(resp), media_type="application/xml")

    elif state == 'name_vip':
        temp_data[sender]['name'] = incoming_msg
        msg.body(f"Hola {incoming_msg}, ¿cuántas personas?")
        conversational_state[sender] = 'cant_vip'

    elif state == 'cant_vip':
        if msg_lower.isdigit():
            cant = int(msg_lower)
            data = temp_data[sender]
            rrpp_final = data.get('rrpp_origen', rrpp_detectado)
            
            res = Reserva(whatsapp_id=sender, nombre_completo=data['name']+" (VIP)", tipo_entrada="Mesa VIP", cantidad=cant, confirmada=True, rrpp_asignado=rrpp_final)
            db.add(res)
            db.commit()
            
            msg.body(f"🥂 *CONFIRMADO*\nLista VIP para {data['name']}.\nPresentate en puerta.")
            conversational_state[sender] = 'start'
            temp_data[sender] = {}
        else:
            msg.body("Solo números.")

    return Response(content=str(resp), media_type="application/xml")

# --- 4. PANEL DE CONTROL (VISUAL) ---
@app.get("/panel", response_class=HTMLResponse)
def ver_panel(db: Session = Depends(get_db)):
    reservas = db.query(Reserva).order_by(Reserva.id.desc()).all()
    
    # Cálculos para Gráficos
    vip = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada == 'Mesa VIP').scalar() or 0
    gen = db.query(func.count(Reserva.id)).filter(Reserva.tipo_entrada == 'General').scalar() or 0
    
    filas = ""
    for r in reservas:
        filas += f"<tr><td>{r.id}</td><td>{r.fecha_reserva.strftime('%H:%M')}</td><td>{r.whatsapp_id}</td><td>{r.nombre_completo}</td><td>{r.tipo_entrada}</td><td>{r.cantidad}</td><td>{r.rrpp_asignado}</td></tr>"

    return f"""
    <html>
    <head>
        <title>MOSCU Admin</title>
        <meta http-equiv="refresh" content="5">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body {{ background: #121212; color: #fff; font-family: sans-serif; padding: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #333; padding: 10px; text-align: left; }}
            th {{ background: #333; }}
            .chart-box {{ width: 300px; margin: 0 auto; }}
        </style>
    </head>
    <body>
        <h1>🦁 MOSCU Live Panel</h1>
        <div class="chart-box"><canvas id="miGrafico"></canvas></div>
        <table>
            <tr><th>ID</th><th>Hora</th><th>Whatsapp</th><th>Nombre</th><th>Tipo</th><th>Pax</th><th>RRPP</th></tr>
            {filas}
        </table>
        <script>
            new Chart(document.getElementById('miGrafico'), {{
                type: 'doughnut',
                data: {{ labels: ['General', 'VIP'], datasets: [{{ data: [{gen}, {vip}], backgroundColor: ['#3498db', '#e67e22'] }}] }}
            }});
        </script>
    </body>
    </html>
    """