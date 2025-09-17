import streamlit as st
import sqlite3
import pandas as pd
import datetime
import random
from gtts import gTTS
from streamlit_autorefresh import st_autorefresh
import matplotlib.pyplot as plt
from difflib import get_close_matches

# ----------------- DB SETUP -----------------
conn = sqlite3.connect("hospital.db", check_same_thread=False)
c = conn.cursor()

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

# ----------------- FUNCTIONS -----------------
def generate_ticket():
    return f"T{datetime.datetime.now().strftime('%H%M%S')}"

def add_patient(first_name, middle_name, surname, age, gender):
    c.execute("INSERT INTO patients (first_name, middle_name, surname, age, gender) VALUES (?, ?, ?, ?, ?)",
              (first_name, middle_name, surname, age, gender))
    conn.commit()
    return c.lastrowid

def add_to_queue(patient_id):
    ticket = generate_ticket()
    entry_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO queue (patient_id, ticket_number, entry_time, location) VALUES (?, ?, ?, ?)",
              (patient_id, ticket, entry_time, "Entry"))
    conn.commit()
    return ticket

def update_triage(patient_id, weight, height, bp):
    c.execute("UPDATE patients SET weight=?, height=?, bp=? WHERE id=?", (weight, height, bp, patient_id))
    c.execute("UPDATE queue SET location='Triage', destination='Consultation' WHERE patient_id=?", (patient_id,))
    conn.commit()

def update_doctor(patient_id, condition, destination):
    exit_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE patients SET condition=? WHERE id=?", (condition, patient_id))
    c.execute("UPDATE queue SET location='Doctor', destination=?, exit_time=? WHERE patient_id=?",
              (destination, exit_time, patient_id))
    conn.commit()

def mark_done(patient_id, section):
    exit_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("UPDATE queue SET location=?, status='done', exit_time=? WHERE patient_id=?",
              (section, exit_time, patient_id))
    conn.commit()

def get_queue():
    return pd.read_sql("""
        SELECT q.queue_id, q.ticket_number,
               p.first_name || ' ' || p.middle_name || ' ' || p.surname as full_name,
               p.age, p.gender, p.weight, p.height, p.bp, p.condition,
               q.location, q.status, q.destination, q.entry_time, q.exit_time
        FROM queue q
        JOIN patients p ON q.patient_id = p.id
        ORDER BY q.queue_id ASC
    """, conn)

def announce_patient(ticket, name, destination):
    text = f"Now serving ticket number {ticket}, {name}. Please proceed to {destination}."
    tts = gTTS(text=text, lang="en")
    filename = "announcement.mp3"
    tts.save(filename)
    return filename

# ----------------- STREAMLIT APP -----------------
st.set_page_config(page_title="Smart Queue System", page_icon="🏥", layout="wide")

menu = st.sidebar.radio("📌 Navigation", 
    ["Home", "About", "Kiosk (Entry)", "TV Display", "Triage", "Doctor Panel", 
     "Pharmacy", "Lab", "Payment", "Analytics", "Chatbot", "FAQs", "Contacts"])

# ----------------- PAGES -----------------
if menu == "Home":
    st.title("🏥 Smart Queue & Patient Journey Tracking")
    st.write("Welcome to the Hospital Smart Queue System. This app helps manage patients from entry to exit.")

elif menu == "About":
    st.title("ℹ️ About")
    st.write("""
    This Smart Queue Management System was built to streamline patient flow:  
    - 🎟 Kiosk → Patient self-registration  
    - 📺 TV Display → Queue management with announcements  
    - 📋 Triage → Vitals recording  
    - 👨‍⚕️ Doctor Panel → Consultation & referral  
    - 💊 Pharmacy / 🧪 Lab / 💵 Payment → Patient completion  
    """)

elif menu == "Kiosk (Entry)":
    st.title("🎟 Patient Kiosk (Entry)")
    first_name = st.text_input("First Name")
    middle_name = st.text_input("Middle Name")
    surname = st.text_input("Surname")
    age = st.number_input("Age", 0, 120)
    gender = st.selectbox("Gender", ["Male", "Female", "Other"])
    if st.button("Generate Ticket"):
        pid = add_patient(first_name, middle_name, surname, age, gender)
        ticket = add_to_queue(pid)
        st.success(f"✅ Ticket generated: {ticket}. Please wait for triage.")

elif menu == "TV Display":
    st.title("📺 Waiting Room Display")
    st_autorefresh(interval=7000, key="tvdisplay")
    current = pd.read_sql("""
        SELECT q.ticket_number,
               p.first_name || ' ' || p.middle_name || ' ' || p.surname as full_name,
               q.destination
        FROM queue q
        JOIN patients p ON q.patient_id = p.id
        WHERE q.status='done'
        ORDER BY q.queue_id DESC
        LIMIT 1
    """, conn)

    if not current.empty:
        ticket = current["ticket_number"].iloc[0]
        name = current["full_name"].iloc[0]
        destination = current["destination"].iloc[0] if current["destination"].iloc[0] else "Triage"
        st.markdown(
            f"<h1 style='text-align:center;'>Now Serving</h1>"
            f"<h2 style='text-align:center; color:red; animation: blinker 1s infinite;'>#{ticket} - {name}</h2>"
            f"<h3 style='text-align:center; color:blue;'>Proceed to {destination}</h3>",
            unsafe_allow_html=True)
        audio_file = announce_patient(ticket, name, destination)
        st.audio(open(audio_file, "rb").read(), format="audio/mp3", autoplay=True)
    else:
        st.info("⏳ Waiting for patients...")

    tips = ["💧 Drink water", "🍎 Eat fruits", "🏃‍♂️ Exercise daily", "🧘 Meditate", "💉 Get vaccinated"]
    st.markdown(f"<p style='text-align:center; font-size:20px; color:green;'>{random.choice(tips)}</p>", unsafe_allow_html=True)

elif menu == "Triage":
    st.title("📋 Triage Station (Login Required)")
    if "triage_logged" not in st.session_state:
        st.session_state.triage_logged = False
    if not st.session_state.triage_logged:
        pw = st.text_input("Triage Password", type="password")
        if st.button("Login"):
            if pw == "triage123":
                st.session_state.triage_logged = True
                st.success("✅ Triage login successful")
            else:
                st.error("❌ Wrong password")
    else:
        pid = st.number_input("Patient ID", step=1, min_value=1)
        weight = st.number_input("Weight (kg)")
        height = st.number_input("Height (cm)")
        bp = st.text_input("Blood Pressure")
        if st.button("Save Triage"):
            update_triage(pid, weight, height, bp)
            st.success("✅ Patient triaged → Consultation")
        if st.button("Logout"):
            st.session_state.triage_logged = False

elif menu == "Doctor Panel":
    st.title("👨‍⚕️ Doctor Panel (Login Required)")
    if "doctor_logged" not in st.session_state:
        st.session_state.doctor_logged = False
    if not st.session_state.doctor_logged:
        pw = st.text_input("Doctor Password", type="password")
        if st.button("Login"):
            if pw == "doctor123":
                st.session_state.doctor_logged = True
                st.success("✅ Doctor login successful")
            else:
                st.error("❌ Wrong password")
    else:
        pid = st.number_input("Patient ID", step=1, min_value=1)
        condition = st.text_area("Condition / Diagnosis")
        destination = st.selectbox("Send to", ["Pharmacy", "Lab", "Payment"])
        if st.button("Complete Consultation"):
            update_doctor(pid, condition, destination)
            st.success(f"✅ Patient sent to {destination}")
        st.dataframe(get_queue())
        if st.button("Logout"):
            st.session_state.doctor_logged = False

elif menu == "Pharmacy":
    st.title("💊 Pharmacy Dashboard (Login Required)")
    if "pharmacy_logged" not in st.session_state:
        st.session_state.pharmacy_logged = False
    if not st.session_state.pharmacy_logged:
        pw = st.text_input("Pharmacy Password", type="password")
        if st.button("Login"):
            if pw == "pharmacy123":
                st.session_state.pharmacy_logged = True
                st.success("✅ Pharmacy login successful")
            else:
                st.error("❌ Wrong password")
    else:
        df = pd.read_sql("SELECT * FROM queue WHERE destination='Pharmacy' AND status!='done'", conn)
        st.dataframe(df)
        pid = st.number_input("Patient ID", step=1, min_value=1)
        if st.button("Mark as Done"):
            mark_done(pid, "Pharmacy")
            st.success("✅ Patient served at Pharmacy")
        if st.button("Logout"):
            st.session_state.pharmacy_logged = False

elif menu == "Lab":
    st.title("🧪 Lab Dashboard (Login Required)")
    if "lab_logged" not in st.session_state:
        st.session_state.lab_logged = False
    if not st.session_state.lab_logged:
        pw = st.text_input("Lab Password", type="password")
        if st.button("Login"):
            if pw == "lab123":
                st.session_state.lab_logged = True
                st.success("✅ Lab login successful")
            else:
                st.error("❌ Wrong password")
    else:
        df = pd.read_sql("SELECT * FROM queue WHERE destination='Lab' AND status!='done'", conn)
        st.dataframe(df)
        pid = st.number_input("Patient ID", step=1, min_value=1)
        if st.button("Mark as Done"):
            mark_done(pid, "Lab")
            st.success("✅ Patient served at Lab")
        if st.button("Logout"):
            st.session_state.lab_logged = False

elif menu == "Payment":
    st.title("💵 Payment Dashboard (Login Required)")
    if "payment_logged" not in st.session_state:
        st.session_state.payment_logged = False
    if not st.session_state.payment_logged:
        pw = st.text_input("Payment Password", type="password")
        if st.button("Login"):
            if pw == "payment123":
                st.session_state.payment_logged = True
                st.success("✅ Payment login successful")
            else:
                st.error("❌ Wrong password")
    else:
        df = pd.read_sql("SELECT * FROM queue WHERE destination='Payment' AND status!='done'", conn)
        st.dataframe(df)
        pid = st.number_input("Patient ID", step=1, min_value=1)
        if st.button("Mark as Done"):
            mark_done(pid, "Payment")
            st.success("✅ Patient cleared Payment")
        if st.button("Logout"):
            st.session_state.payment_logged = False

elif menu == "Analytics":
    st.title("📊 Analytics Dashboard")
    df = get_queue()
    if not df.empty:
        df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
        df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
        df = df.dropna(subset=["entry_time", "exit_time"])  

        if not df.empty:
            df["wait"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60
            st.metric("Average Wait Time", f"{df['wait'].mean():.1f} min")
            fig, ax = plt.subplots()
            df["destination"].value_counts().plot(kind="bar", ax=ax)
            st.pyplot(fig)
        else:
            st.info("No completed patients yet for analytics.")
    else:
        st.info("No data yet.")

elif menu == "Chatbot":
    st.title("🤖 Hospital Chatbot")
    faq = {
        "register": "📝 Register at the kiosk and get a ticket.",
        "triage": "📋 Triage includes weight, height, and blood pressure checks.",
        "doctor": "👨‍⚕️ Doctor consultation follows triage.",
        "pharmacy": "💊 Go to pharmacy after consultation.",
        "lab": "🧪 Go to lab if doctor refers you.",
        "payment": "💵 Finish at payment counter."
    }
    q = st.text_input("Ask me something...")
    if q:
        match = get_close_matches(q.lower(), faq.keys(), n=1, cutoff=0.4)
        if match:
            st.write(faq[match[0]])
        else:
            st.write("I’m still learning 🤖. Please ask reception.")

elif menu == "FAQs":
    st.title("❓ Frequently Asked Questions")
    st.write("""
    **Q: How do I register?**  
    A: Use the kiosk at the entrance.  

    **Q: What happens at triage?**  
    A: Vitals are recorded (weight, height, BP).  

    **Q: Where do I go after the doctor?**  
    A: You’ll be directed to Pharmacy, Lab, or Payment.  
    """)

elif menu == "Contacts":
    st.title("📞 Contact Us")
    st.markdown("""
    **📧 Email:** [marrionwahome974@gmail.com](mailto:marrionwahome974@gmail.com)  
    **📱 Phone:** +254111838986  
    """)
    st.info("We’re here to support you with any issues or inquiries.")

  

# (keep your Triage, Doctor, Pharmacy, Lab, Payment, Chatbot, FAQ, Contacts code unchanged)
