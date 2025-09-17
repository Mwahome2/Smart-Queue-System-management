# app.py - Full Smart Queue System (complete)
import streamlit as st
import sqlite3
import pandas as pd
import datetime
import random
import os
from gtts import gTTS
from streamlit_autorefresh import st_autorefresh
import matplotlib.pyplot as plt
from difflib import get_close_matches

# ----------------- DB SETUP & MIGRATION -----------------
DB_PATH = "hospital.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()

# Helper: check columns for a table
def table_columns(table):
    c.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in c.fetchall()]

# If patients table exists with old schema (name) -> migrate to new schema
existing_tables = []
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
existing_tables = [r[0] for r in c.fetchall()]

if "patients" in existing_tables:
    cols = table_columns("patients")
    if "name" in cols and "first_name" not in cols:
        # rename and migrate rows with simple split
        c.execute("ALTER TABLE patients RENAME TO patients_old")
        conn.commit()

        c.execute('''
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            middle_name TEXT,
            surname TEXT,
            age INTEGER,
            gender TEXT,
            weight REAL,
            height REAL,
            bp TEXT,
            condition TEXT
        )
        ''')
        conn.commit()

        # Copy rows from old table, split 'name' into parts
        c.execute("SELECT id, name, age, gender, condition FROM patients_old")
        old_rows = c.fetchall()
        for row in old_rows:
            _, fullname, age, gender, condition = row
            if fullname and isinstance(fullname, str):
                parts = fullname.strip().split()
                first = parts[0] if len(parts) >= 1 else ""
                surname = parts[-1] if len(parts) >= 2 else ""
                middle = " ".join(parts[1:-1]) if len(parts) > 2 else ""
            else:
                first = middle = surname = ""
            c.execute("""
                INSERT INTO patients (first_name, middle_name, surname, age, gender, condition)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (first, middle, surname, age, gender, condition))
        conn.commit()

        # Optionally drop old table
        c.execute("DROP TABLE IF EXISTS patients_old")
        conn.commit()
else:
    # create fresh patients table if not exists
    c.execute('''
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT,
        middle_name TEXT,
        surname TEXT,
        age INTEGER,
        gender TEXT,
        weight REAL,
        height REAL,
        bp TEXT,
        condition TEXT
    )
    ''')
    conn.commit()

# Ensure queue table exists and has the new columns
if "queue" not in existing_tables:
    c.execute('''
    CREATE TABLE IF NOT EXISTS queue (
        queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        ticket_number TEXT,
        entry_time TEXT,
        exit_time TEXT,
        location TEXT,
        status TEXT DEFAULT "waiting",
        destination TEXT,
        FOREIGN KEY(patient_id) REFERENCES patients(id)
    )
    ''')
    conn.commit()
else:
    # if old queue schema uses 'time' instead of 'entry_time', migrate
    qcols = table_columns("queue")
    # add missing columns using ALTER TABLE (safe)
    needed = ["ticket_number", "entry_time", "exit_time", "location", "destination"]
    for col in needed:
        if col not in qcols:
            c.execute(f"ALTER TABLE queue ADD COLUMN {col} TEXT")
    conn.commit()
    # if old `time` exists and entry_time empty -> copy
    if "time" in qcols:
        # copy time->entry_time only where entry_time is null
        c.execute("UPDATE queue SET entry_time = time WHERE (entry_time IS NULL OR entry_time='') AND time IS NOT NULL")
        conn.commit()

# ----------------- UTILS -----------------
def generate_ticket():
    # ticket uses timestamp to reduce collisions
    return f"T{datetime.datetime.now().strftime('%y%m%d%H%M%S%f')[-12:]}"

def split_fullname(fullname):
    if not fullname or not isinstance(fullname, str):
        return "", "", ""
    parts = fullname.strip().split()
    if len(parts) == 1:
        return parts[0], "", ""
    elif len(parts) == 2:
        return parts[0], "", parts[1]
    else:
        return parts[0], " ".join(parts[1:-1]), parts[-1]

def safe_get(df, col, default=""):
    try:
        val = df[col]
        return val
    except Exception:
        return default

# ----------------- CRUD / FLOW FUNCTIONS -----------------
def add_patient(first_name, middle_name, surname, age, gender):
    c.execute("INSERT INTO patients (first_name, middle_name, surname, age, gender) VALUES (?, ?, ?, ?, ?)",
              (first_name, middle_name, surname, age, gender))
    conn.commit()
    return c.lastrowid

def update_patient(pid, first_name, middle_name, surname, age, gender, weight=None, height=None, bp=None, condition=None):
    # Allow None values
    c.execute("""
        UPDATE patients 
        SET first_name=?, middle_name=?, surname=?, age=?, gender=?, weight=?, height=?, bp=?, condition=?
        WHERE id=?
    """, (first_name, middle_name, surname, age, gender, weight, height, bp, condition, pid))
    conn.commit()

def add_to_queue(patient_id, destination=None):
    ticket = generate_ticket()
    entry_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    loc = "Entry"
    c.execute("INSERT INTO queue (patient_id, ticket_number, entry_time, location, destination, status) VALUES (?, ?, ?, ?, ?, ?)",
              (patient_id, ticket, entry_time, loc, destination or "Triage", "waiting"))
    conn.commit()
    return ticket

def update_triage(patient_id, weight, height, bp):
    # update patient vitals and move queue location to 'Triage' and destination -> Consultation
    c.execute("UPDATE patients SET weight=?, height=?, bp=? WHERE id=?", (weight, height, bp, patient_id))
    c.execute("UPDATE queue SET location='Triage', destination='Consultation' WHERE patient_id=?", (patient_id,))
    conn.commit()

def update_doctor(patient_id, condition, destination):
    # record diagnosis and forward to destination (Pharmacy/Lab/Payment). status remains 'waiting' until destination marks done.
    c.execute("UPDATE patients SET condition=? WHERE id=?", (condition, patient_id))
    c.execute("UPDATE queue SET location='Doctor', destination=?, status='waiting' WHERE patient_id=?", (destination, patient_id))
    conn.commit()

def mark_done_by_queue(queue_id, section):
    # mark a queue row as done (used by Pharmacy/Lab/Payment). set exit_time
    exit_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE queue SET location=?, status='done', exit_time=? WHERE queue_id=?", (section, exit_time, queue_id))
    conn.commit()

def get_queue_df():
    try:
        return pd.read_sql("""
            SELECT q.queue_id, q.patient_id, q.ticket_number,
                   p.first_name || ' ' || IFNULL(p.middle_name,'') || ' ' || IFNULL(p.surname,'') as full_name,
                   p.age, p.gender, p.weight, p.height, p.bp, p.condition,
                   q.location, q.status, q.destination, q.entry_time, q.exit_time
            FROM queue q
            LEFT JOIN patients p ON q.patient_id = p.id
            ORDER BY q.queue_id ASC
        """, conn)
    except Exception as e:
        st.error(f"DB error: {e}")
        return pd.DataFrame()

def announce_patient(ticket, name, destination):
    text = f"Now serving ticket number {ticket}, {name}. Please proceed to {destination}."
    tts = gTTS(text=text, lang="en")
    fname = "announcement.mp3"
    tts.save(fname)
    return fname

# ----------------- STREAMLIT UI -----------------
st.set_page_config(page_title="Smart Queue System", page_icon="🏥", layout="wide")
menu = st.sidebar.radio("📌 Navigation",
                        ["Home", "About", "Kiosk (Entry)", "TV Display", "Triage", "Doctor Panel",
                         "Pharmacy", "Lab", "Payment", "Patient Records", "Analytics", "Chatbot", "FAQs", "Contacts"])

# ---------- HOME ----------
if menu == "Home":
    st.title("🏥 Smart Queue & Patient Journey Tracking")
    col1, col2 = st.columns([2,1])
    with col1:
        st.write("Welcome — the system tracks patients from Entry → Triage → Doctor → Pharmacy/Lab → Payment → Exit.")
        st.markdown("- Patients register at the kiosk and receive a **ticket**.")
        st.markdown("- Triage records vitals (weight/height/BP).")
        st.markdown("- Doctor records condition and assigns destination.")
        st.markdown("- Destination staff (Pharmacy/Lab/Payment) mark patients done.")
    with col2:
        st.write("Quick stats")
        qdf = get_queue_df()
        st.metric("Total Tickets", len(qdf))
        st.metric("Waiting", int((qdf['status'] == 'waiting').sum() if not qdf.empty else 0))
        st.metric("Completed", int((qdf['status'] == 'done').sum() if not qdf.empty else 0))

# ---------- ABOUT ----------
elif menu == "About":
    st.title("ℹ️ About")
    st.write("""
    Smart Queue System — a lightweight patient flow manager for clinics/hospitals.
    Flow: **Kiosk → TV → Triage → Doctor → Pharmacy/Lab → Payment**.
    """)

# ---------- KIOSK ----------
elif menu == "Kiosk (Entry)":
    st.title("🎟 Patient Kiosk (Entry)")
    with st.form("kiosk_form", clear_on_submit=True):
        first_name = st.text_input("First Name")
        middle_name = st.text_input("Middle Name (optional)")
        surname = st.text_input("Surname")
        age = st.number_input("Age", 0, 120)
        gender = st.selectbox("Gender", ["Male", "Female", "Other"])
        submitted = st.form_submit_button("Generate Ticket")
        if submitted:
            pid = add_patient(first_name.strip(), middle_name.strip(), surname.strip(), int(age), gender)
            ticket = add_to_queue(pid)
            st.success(f"✅ Ticket generated: **{ticket}**. Please move to waiting area / TV display.")
            st.info("Triage staff will call you when ready.")

# ---------- TV DISPLAY ----------
elif menu == "TV Display":
    st.title("📺 Waiting Room Display")
    st_autorefresh(interval=7000, key="tvdisplay")

    # Choose next to call: earliest waiting queue (status='waiting')
    next_df = pd.read_sql("""
        SELECT q.queue_id, q.ticket_number,
               p.first_name || ' ' || IFNULL(p.middle_name,'') || ' ' || IFNULL(p.surname,'') as full_name,
               q.destination
        FROM queue q
        LEFT JOIN patients p ON q.patient_id = p.id
        WHERE q.status='waiting'
        ORDER BY q.queue_id ASC
        LIMIT 1
    """, conn)

    if not next_df.empty:
        ticket = next_df["ticket_number"].iloc[0]
        name = next_df["full_name"].iloc[0] or "Patient"
        destination = next_df["destination"].iloc[0] if next_df["destination"].iloc[0] else "Triage"
        # Animated display
        st.markdown("""
            <style>
            @keyframes blinker { 50% { opacity: 0; } }
            .blinking { animation: blinker 1.2s linear infinite; color: red; font-size:60px; text-align:center; }
            .tv-title { text-align:center; font-size:36px; margin-bottom:0.2rem; }
            .tv-sub { text-align:center; font-size:24px; color:blue; }
            </style>
        """, unsafe_allow_html=True)

        st.markdown(f"<div class='tv-title'>Now Serving</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='blinking'>Ticket {ticket} — {name}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='tv-sub'>Please proceed to {destination}</div>", unsafe_allow_html=True)

        # audio announcement (generate/play)
        try:
            audio_file = announce_patient(ticket, name, destination)
            audio_bytes = open(audio_file, "rb").read()
            st.audio(audio_bytes, format="audio/mp3", autoplay=True)
            # remove file to keep workspace clean
            try:
                os.remove(audio_file)
            except Exception:
                pass
        except Exception as e:
            st.warning("Audio announcement unavailable.")
            st.write(f"(debug: {e})")
    else:
        st.info("⏳ No waiting patients at the moment. Please relax and enjoy health tips.")

    # rotating health tips / small animation
    tips = [
        "💧 Drink at least 8 glasses of water daily.",
        "🍎 Eat more fruits and vegetables for better immunity.",
        "🏃 Exercise 30 minutes daily for heart health.",
        "🧘 Take deep breaths to reduce stress.",
        "💉 Keep your vaccinations up to date."
    ]
    st.markdown(f"<p style='text-align:center; font-size:20px; color:green;'>{random.choice(tips)}</p>", unsafe_allow_html=True)

# ---------- TRIAGE ----------
elif menu == "Triage":
    st.title("📋 Triage Station (Login Required)")
    if "triage_logged" not in st.session_state:
        st.session_state.triage_logged = False

    if not st.session_state.triage_logged:
        pw = st.text_input("Triage Password", type="password")
        if st.button("Login as Triage"):
            if pw == "triage123":
                st.session_state.triage_logged = True
                st.success("✅ Triage login successful")
            else:
                st.error("❌ Wrong password")
    else:
        st.subheader("Triage - record vitals")
        qdf = get_queue_df()
        # show waiting patients in Entry or Triage
        waiting = qdf[(qdf['status'] == 'waiting') & (qdf['location'].isin(['Entry','Triage']))]
        st.write("Patients waiting for triage:")
        st.dataframe(waiting[["queue_id","ticket_number","patient_id","full_name","location","entry_time"]])

        with st.form("triage_form"):
            qid = st.number_input("Queue ID to triage", min_value=1, step=1)
            pid = st.number_input("Patient ID", min_value=1, step=1)
            weight = st.number_input("Weight (kg)", value=0.0)
            height = st.number_input("Height (cm)", value=0.0)
            bp = st.text_input("BP (e.g., 120/80)")
            triage_submit = st.form_submit_button("Save Triage Data & Move to Consultation")
            if triage_submit:
                # update triage info and queue location
                update_triage(int(pid), float(weight), float(height), bp)
                st.success("✅ Triage saved. Patient moved to Consultation queue.")

        if st.button("Logout Triage"):
            st.session_state.triage_logged = False
            st.warning("Logged out")

# ---------- DOCTOR PANEL ----------
elif menu == "Doctor Panel":
    st.title("👨‍⚕️ Doctor Panel (Login Required)")
    if "doctor_logged" not in st.session_state:
        st.session_state.doctor_logged = False

    if not st.session_state.doctor_logged:
        pw = st.text_input("Doctor Password", type="password")
        if st.button("Login as Doctor"):
            if pw == "doctor123":
                st.session_state.doctor_logged = True
                st.success("✅ Doctor login successful")
            else:
                st.error("❌ Wrong password")
    else:
        st.subheader("Patients waiting for consultation")
        qdf = get_queue_df()
        consult_wait = qdf[(qdf['status']=='waiting') & (qdf['destination'].isin(['Consultation', None]))]
        st.dataframe(consult_wait[["queue_id","ticket_number","patient_id","full_name","entry_time"]])

        with st.form("doctor_form"):
            qid = st.number_input("Queue ID", min_value=1, step=1)
            pid = st.number_input("Patient ID", min_value=1, step=1)
            condition = st.text_area("Condition / Diagnosis")
            destination = st.selectbox("Send patient to", ["Pharmacy", "Lab", "Payment"])
            doctor_submit = st.form_submit_button("Complete Consultation & Forward")
            if doctor_submit:
                update_doctor(int(pid), condition, destination)
                st.success(f"✅ Patient forwarded to {destination}")

        if st.button("Logout Doctor"):
            st.session_state.doctor_logged = False
            st.warning("Logged out")

# ---------- PHARMACY ----------
elif menu == "Pharmacy":
    st.title("💊 Pharmacy Dashboard (Login Required)")
    if "pharmacy_logged" not in st.session_state:
        st.session_state.pharmacy_logged = False

    if not st.session_state.pharmacy_logged:
        pw = st.text_input("Pharmacy Password", type="password")
        if st.button("Login as Pharmacy"):
            if pw == "pharmacy123":
                st.session_state.pharmacy_logged = True
                st.success("✅ Pharmacy login successful")
            else:
                st.error("❌ Wrong password")
    else:
        st.subheader("Patients to serve at Pharmacy")
        df = pd.read_sql("SELECT q.queue_id, q.patient_id, q.ticket_number, q.destination, p.first_name||' '||IFNULL(p.surname,'') as name FROM queue q LEFT JOIN patients p ON q.patient_id=p.id WHERE q.destination='Pharmacy' AND q.status!='done' ORDER BY q.queue_id", conn)
        st.dataframe(df)
        qid = st.number_input("Queue ID to mark done", min_value=1, step=1)
        if st.button("Mark Pharmacy Done"):
            mark_done_by_queue(int(qid), "Pharmacy")
            st.success("✅ Marked as done at Pharmacy")
        if st.button("Logout Pharmacy"):
            st.session_state.pharmacy_logged = False

# ---------- LAB ----------
elif menu == "Lab":
    st.title("🧪 Lab Dashboard (Login Required)")
    if "lab_logged" not in st.session_state:
        st.session_state.lab_logged = False

    if not st.session_state.lab_logged:
        pw = st.text_input("Lab Password", type="password")
        if st.button("Login as Lab"):
            if pw == "lab123":
                st.session_state.lab_logged = True
                st.success("✅ Lab login successful")
            else:
                st.error("❌ Wrong password")
    else:
        st.subheader("Patients to serve at Lab")
        df = pd.read_sql("SELECT q.queue_id, q.patient_id, q.ticket_number, q.destination, p.first_name||' '||IFNULL(p.surname,'') as name FROM queue q LEFT JOIN patients p ON q.patient_id=p.id WHERE q.destination='Lab' AND q.status!='done' ORDER BY q.queue_id", conn)
        st.dataframe(df)
        qid = st.number_input("Queue ID to mark done (Lab)", min_value=1, step=1)
        if st.button("Mark Lab Done"):
            mark_done_by_queue(int(qid), "Lab")
            st.success("✅ Marked as done at Lab")
        if st.button("Logout Lab"):
            st.session_state.lab_logged = False

# ---------- PAYMENT ----------
elif menu == "Payment":
    st.title("💵 Payment Dashboard (Login Required)")
    if "payment_logged" not in st.session_state:
        st.session_state.payment_logged = False

    if not st.session_state.payment_logged:
        pw = st.text_input("Payment Password", type="password")
        if st.button("Login as Payment"):
            if pw == "payment123":
                st.session_state.payment_logged = True
                st.success("✅ Payment login successful")
            else:
                st.error("❌ Wrong password")
    else:
        st.subheader("Patients to clear Payment")
        df = pd.read_sql("SELECT q.queue_id, q.patient_id, q.ticket_number, q.destination, p.first_name||' '||IFNULL(p.surname,'') as name FROM queue q LEFT JOIN patients p ON q.patient_id=p.id WHERE q.destination='Payment' AND q.status!='done' ORDER BY q.queue_id", conn)
        st.dataframe(df)
        qid = st.number_input("Queue ID to mark done (Payment)", min_value=1, step=1)
        if st.button("Mark Payment Done"):
            mark_done_by_queue(int(qid), "Payment")
            st.success("✅ Marked as done at Payment")
        if st.button("Logout Payment"):
            st.session_state.payment_logged = False

# ---------- PATIENT RECORDS ----------
elif menu == "Patient Records":
    st.title("📂 Patient Records")
    # Search bar
    search = st.text_input("Search by First name / Surname / Ticket (partial OK)")
    qdf = get_queue_df()
    pdf = pd.read_sql("SELECT * FROM patients", conn)
    if search:
        term = f"%{search.strip().lower()}%"
        # search both patients and queue
        res_pat = pd.read_sql("SELECT * FROM patients WHERE lower(first_name) LIKE ? OR lower(surname) LIKE ?", conn, params=(term,term))
        res_queue = pd.read_sql("SELECT q.queue_id, q.ticket_number, p.* FROM queue q LEFT JOIN patients p ON q.patient_id=p.id WHERE lower(q.ticket_number) LIKE ?", conn, params=(term,))
        st.write("Patients matching name:")
        st.dataframe(res_pat)
        st.write("Queue rows matching ticket:")
        st.dataframe(res_queue)
    else:
        st.dataframe(pdf)

    st.subheader("📤 Upload CSV / Excel to add/update patients")
    file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])
    if file is not None:
        if file.name.endswith(".csv"):
            new_df = pd.read_csv(file)
        else:
            new_df = pd.read_excel(file)
        st.write("Preview:")
        st.dataframe(new_df.head())

        if st.button("Save Uploaded Data"):
            # Expect columns: first_name/middle_name/surname/age/gender/weight/height/bp/condition
            for _, row in new_df.iterrows():
                # support full 'name' column by splitting
                if "name" in row and pd.notna(row["name"]) and ("first_name" not in row or pd.isna(row.get("first_name"))):
                    fn, mn, sn = split_fullname(row["name"])
                else:
                    fn = row.get("first_name", "") or ""
                    mn = row.get("middle_name", "") or ""
                    sn = row.get("surname", "") or ""
                age = int(row.get("age", 0)) if pd.notna(row.get("age", None)) else 0
                gender = row.get("gender", "") or ""
                # Check existence by name+age
                c.execute("SELECT id FROM patients WHERE first_name=? AND surname=? AND age=?", (fn, sn, age))
                existing = c.fetchone()
                if existing:
                    update_patient(existing[0], fn, mn, sn, age, gender,
                                   row.get("weight", None), row.get("height", None), row.get("bp", None), row.get("condition", None))
                else:
                    add_patient(fn, mn, sn, age, gender)
            st.success("✅ Uploaded data saved/merged.")

    st.subheader("✏️ Manual update")
    pid = st.number_input("Enter Patient ID to fetch", step=1, min_value=1)
    if st.button("Fetch Patient"):
        pat = pd.read_sql("SELECT * FROM patients WHERE id=?", conn, params=(pid,))
        if not pat.empty:
            p = pat.iloc[0]
            fn = st.text_input("First Name", p["first_name"])
            mn = st.text_input("Middle Name", p["middle_name"] if pd.notna(p["middle_name"]) else "")
            sn = st.text_input("Surname", p["surname"] if pd.notna(p["surname"]) else "")
            age = st.number_input("Age", 0, 120, int(p["age"]) if pd.notna(p["age"]) else 0)
            gender = st.selectbox("Gender", ["Male", "Female", "Other"], index=["Male","Female","Other"].index(p["gender"]) if p["gender"] in ["Male","Female","Other"] else 0)
            weight = st.number_input("Weight (kg)", value=float(p["weight"]) if pd.notna(p["weight"]) else 0.0)
            height = st.number_input("Height (cm)", value=float(p["height"]) if pd.notna(p["height"]) else 0.0)
            bp = st.text_input("BP", p["bp"] if pd.notna(p["bp"]) else "")
            condition = st.text_area("Condition", p["condition"] if pd.notna(p["condition"]) else "")
            if st.button("Update Patient Record"):
                update_patient(pid, fn, mn, sn, int(age), gender, float(weight), float(height), bp, condition)
                st.success("✅ Patient record updated.")

# ---------- ANALYTICS ----------
elif menu == "Analytics":
    st.title("📊 Analytics Dashboard")
    df = get_queue_df()
    if not df.empty:
        df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
        df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
        # Average wait uses only completed visits
        done = df.dropna(subset=["entry_time", "exit_time"]).copy()
        if not done.empty:
            done["wait_minutes"] = (done["exit_time"] - done["entry_time"]).dt.total_seconds() / 60
            st.metric("Average Wait Time (completed)", f"{done['wait_minutes'].mean():.1f} min")
            # Patients per destination chart
            fig1, ax1 = plt.subplots()
            done["destination"].fillna("Unknown").value_counts().plot(kind="bar", ax=ax1)
            ax1.set_ylabel("Number of patients")
            st.pyplot(fig1)
        else:
            st.info("No completed records to compute average wait time yet.")

        # Queue load over time (entry hour)
        df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
        df["hour"] = df["entry_time"].dt.hour
        load = df.groupby("hour").size()
        if not load.empty:
            fig2, ax2 = plt.subplots()
            load.plot(kind="line", marker="o", ax=ax2)
            ax2.set_xlabel("Hour of day")
            ax2.set_ylabel("Number of arrivals")
            st.pyplot(fig2)
        else:
            st.info("Not enough arrival data for hourly chart.")
    else:
        st.info("No queue data yet for analytics.")

# ---------- CHATBOT ----------
elif menu == "Chatbot":
    st.title("🤖 Hospital Chatbot (FAQ)")
    faq = {
        "register": "📝 Register at the kiosk and get a ticket.",
        "how to register": "📝 Register at the kiosk and get a ticket.",
        "triage": "📋 Triage includes weight, height, and blood pressure checks.",
        "consultation": "👨‍⚕️ Consultations happen after triage. The doctor will call you.",
        "pharmacy": "💊 Pharmacy is located after consultation.",
        "lab": "🧪 Lab is on site; doctor will refer if needed.",
        "payment": "💵 Payment counter is at the exit; please proceed there when prompted."
    }
    q = st.text_input("Ask me something...")
    if q:
        match = get_close_matches(q.lower(), faq.keys(), n=1, cutoff=0.4)
        if match:
            st.info(faq[match[0]])
        else:
            st.info("I’m still learning 🤖. For complex questions please ask the reception desk.")

# ---------- FAQs ----------
elif menu == "FAQs":
    st.title("❓ Frequently Asked Questions")
    st.write("""
    **Q: How do I register?**  
    A: Use the kiosk at the entrance and you'll get a ticket number.

    **Q: What happens at triage?**  
    A: Vitals (weight, height, BP) are measured and patient is queued for doctor.

    **Q: Where do I go after the doctor?**  
    A: You may be directed to Pharmacy, Lab or Payment depending on the doctor's instructions.
    """)

# ---------- CONTACTS ----------
elif menu == "Contacts":
    st.title("📞 Contact Us")
    st.markdown("""
    **📧 Email:** [marrionwahome974@gmail.com](mailto:marrionwahome974@gmail.com)  
    **📱 Phone:** +254111838986  
    """)
    st.info("We’re here to support you with any issues or inquiries.")





  

