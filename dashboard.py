import streamlit as st
import csv
import os
from collections import defaultdict
from datetime import datetime, date
from fpdf import FPDF
from groq import Groq
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────
st.set_page_config(
    page_title="MediCare Pharmacy Dashboard",
    page_icon="💊",
    layout="wide"
)

FOLDER   = r"C:\Users\10044\OneDrive\Project\pharma_agent"
FONT_DIR = FOLDER + "\\fonts\\"
load_dotenv(FOLDER + "\\.env")
api_key = os.getenv("GROQ_API_KEY") or st.secrets.get("GROQ_API_KEY", "")
client = Groq(api_key=api_key)

# ── Helpers ───────────────────────────────────────────────
def load_patients():
    filepath = os.path.join(FOLDER, "patients.csv")
    patients = defaultdict(lambda: {
        "name": "", "age": "", "phone": "",
        "language": "", "drugs": []
    })
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            pid = row["patient_id"]
            patients[pid]["name"]     = row["name"]
            patients[pid]["age"]      = row["age"]
            patients[pid]["phone"]    = row["phone"]
            patients[pid]["language"] = row["language"]
            patients[pid]["drugs"].append({
                "drug_name":  row["drug_name"],
                "dosage":     row["dosage"],
                "frequency":  row["frequency"],
                "refill_due": row["refill_due"],
                "condition":  row["condition"],
                "notes":      row["notes"]
            })
    return dict(patients)

def days_until_refill(refill_date_str):
    try:
        refill_date = datetime.strptime(refill_date_str, "%Y-%m-%d").date()
        return (refill_date - date.today()).days
    except:
        return 999

def get_patient_status(patient):
    for drug in patient["drugs"]:
        days = days_until_refill(drug["refill_due"])
        if days < 0:   return "OVERDUE"
        if days <= 3:  return "URGENT"
        if days <= 7:  return "DUE SOON"
    return "NORMAL"

def status_badge(status):
    colours = {
        "OVERDUE":  ("#FF4444", "white"),
        "URGENT":   ("#FF8800", "white"),
        "DUE SOON": ("#FFB700", "black"),
        "NORMAL":   ("#2D6A4F", "white"),
    }
    bg, fg = colours.get(status, ("#888888", "white"))
    return (
        '<span style="background:' + bg + ';color:' + fg + ';'
        'padding:3px 10px;border-radius:12px;'
        'font-size:12px;font-weight:bold;">' + status + '</span>'
    )

def format_patient_context(patient):
    lines = [
        "Patient Name : " + patient["name"],
        "Age          : " + patient["age"],
        "Language     : " + patient["language"],
        "Prescriptions:",
    ]
    for i, drug in enumerate(patient["drugs"], 1):
        lines.append(
            "  " + str(i) + ". " + drug["drug_name"] + " " + drug["dosage"] +
            " -- " + drug["frequency"] +
            " | Refill due: " + drug["refill_due"] +
            " | Condition: " + drug["condition"] +
            " | Notes: " + drug["notes"]
        )
    return "\n".join(lines)

def clean_for_latin(text):
    """Fallback cleaner for section headers — latin-1 only areas"""
    if not text:
        return ""
    replacements = {
        "\u2014": "-", "\u2013": "-", "\u2018": "'",
        "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2022": "*", "\u2026": "...",
    }
    for char, rep in replacements.items():
        text = text.replace(char, rep)
    return text.encode("latin-1", errors="replace").decode("latin-1")

SERIOUS_SYMPTOMS = [
    "chest pain", "breathless", "unconscious", "faint",
    "bleeding", "severe", "emergency", "hospital",
    "bahut dard", "sans nahi", "behoshi", "khoon"
]

def check_serious_symptoms(text):
    return any(s in text.lower() for s in SERIOUS_SYMPTOMS)

def get_report_files():
    return sorted([f for f in os.listdir(FOLDER) if f.startswith("report_")], reverse=True)

def get_transcript_files():
    return sorted([f for f in os.listdir(FOLDER) if f.startswith("transcript_")], reverse=True)

def generate_summary(transcript_lines, patient):
    transcript_text = "\n".join(transcript_lines)
    prompt = (
        "You are a pharmacy documentation assistant.\n"
        "Read this patient call transcript and return ONLY these sections:\n\n"
        "PATIENT: [name and age]\n"
        "DATE: [today]\n"
        "ADHERENCE: [medication status, missed doses]\n"
        "SIDE EFFECTS: [any symptoms mentioned]\n"
        "HEALTH: [general health]\n"
        "REFILL: [refill requests or confirmations]\n"
        "FLAGS: [pharmacist follow-up needed]\n"
        "STATUS: [one word: NORMAL or MONITOR or ESCALATE]\n\n"
        "One line per section. Plain English only in the summary.\n"
        "Translate any Hindi content to English in your summary.\n"
        "If not mentioned write: Not reported\n\n"
        "TRANSCRIPT:\n" + transcript_text
    )
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a pharmacy documentation assistant. "
                    "Always write summaries in plain English only. "
                    "Translate any Hindi or regional language content to English."
                )
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=400
    )
    return response.choices[0].message.content

def parse_summary(text):
    sections = {
        "PATIENT":      "Not reported",
        "DATE":         date.today().strftime("%d %B %Y"),
        "ADHERENCE":    "Not reported",
        "SIDE EFFECTS": "Not reported",
        "HEALTH":       "Not reported",
        "REFILL":       "Not reported",
        "FLAGS":        "Not reported",
        "STATUS":       "NORMAL"
    }
    for line in text.splitlines():
        for key in sections:
            if line.upper().startswith(key + ":"):
                val = line[len(key)+1:].strip()
                if val:
                    sections[key] = val
    return sections

def generate_pdf(sections, transcript_lines, patient_name, source_file):
    status = sections["STATUS"].strip().upper()
    if "ESCALATE" in status:
        bg, fg = (248, 215, 218), (114, 28, 36)
        status_label = "ESCALATE - Pharmacist Callback Required"
    elif "MONITOR" in status:
        bg, fg = (255, 243, 205), (133, 100, 4)
        status_label = "MONITOR - Follow-up Recommended"
    else:
        bg, fg = (212, 237, 218), (21, 87, 36)
        status_label = "NORMAL - No Action Required"

    # Check if NotoSans fonts are available
    noto_regular = FONT_DIR + "NotoSans-Regular.ttf"
    noto_bold    = FONT_DIR + "NotoSans-Bold.ttf"
    has_noto     = os.path.exists(noto_regular) and os.path.exists(noto_bold)

    class PharmaPDF(FPDF):
        def header(self):
            self.set_fill_color(45, 106, 79)
            self.rect(0, 0, 210, 28, "F")
            self.set_font("Heading", "B", 16)
            self.set_text_color(255, 255, 255)
            self.set_y(8)
            self.cell(0, 8, "MediCare Pharmacy", align="C", new_x="LMARGIN", new_y="NEXT")
            self.set_font("Heading", "", 9)
            self.cell(0, 5, "AI Patient Follow-up Call Report", align="C", new_x="LMARGIN", new_y="NEXT")
            self.set_text_color(0, 0, 0)
            self.ln(8)

        def footer(self):
            self.set_y(-15)
            self.set_font("Heading", "", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10,
                clean_for_latin(
                    "Generated: " + datetime.now().strftime("%d %B %Y, %I:%M %p") +
                    "  |  AI-assisted - review by licensed pharmacist required"
                ),
                align="C"
            )

    pdf = PharmaPDF()

    # Register fonts — NotoSans for Unicode/Hindi, Helvetica fallback
    if has_noto:
        pdf.add_font("Body",    "",  noto_regular, uni=True)
        pdf.add_font("Body",    "B", noto_bold,    uni=True)
        pdf.add_font("Heading", "",  noto_regular, uni=True)
        pdf.add_font("Heading", "B", noto_bold,    uni=True)
        body_font    = "Body"
        heading_font = "Heading"
    else:
        # Fallback to Helvetica — Hindi will show as ? but no crash
        body_font    = "Helvetica"
        heading_font = "Helvetica"

    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Status banner
    pdf.set_fill_color(*bg)
    pdf.set_draw_color(*fg)
    pdf.set_font(heading_font, "B", 13)
    pdf.set_text_color(*fg)
    pdf.set_line_width(0.5)
    pdf.rect(14, pdf.get_y(), 182, 12, "FD")
    pdf.set_xy(14, pdf.get_y() + 2)
    pdf.cell(182, 8, clean_for_latin("STATUS: " + status_label), align="C")
    pdf.ln(16)

    # Patient info box
    pdf.set_fill_color(245, 245, 245)
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.rect(14, pdf.get_y(), 182, 22, "FD")
    pdf.set_xy(16, pdf.get_y() + 3)
    pdf.set_font(heading_font, "B", 10)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(60, 6, clean_for_latin("Patient : " + sections["PATIENT"]))
    pdf.cell(60, 6, clean_for_latin("Date    : " + sections["DATE"]))
    pdf.cell(60, 6, clean_for_latin("Source  : " + source_file[:28]))
    pdf.ln(16)

    # Summary sections — English only (from AI summary)
    for title, key in [
        ("Medication Adherence",  "ADHERENCE"),
        ("Side Effects Reported", "SIDE EFFECTS"),
        ("General Health",        "HEALTH"),
        ("Refill Status",         "REFILL"),
        ("Flags for Pharmacist",  "FLAGS"),
    ]:
        # Green title bar
        pdf.set_fill_color(45, 106, 79)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(heading_font, "B", 10)
        pdf.rect(14, pdf.get_y(), 182, 8, "F")
        pdf.set_xy(16, pdf.get_y() + 1)
        pdf.cell(0, 6, clean_for_latin(title))
        pdf.ln(10)
        # Content — use NotoSans so English renders cleanly
        pdf.set_text_color(50, 50, 50)
        pdf.set_font(body_font, "", 10)
        pdf.set_x(16)
        pdf.multi_cell(178, 6, clean_for_latin(sections[key]))
        pdf.ln(4)

    # Full transcript — NotoSans handles Hindi characters
    pdf.set_fill_color(45, 106, 79)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font(heading_font, "B", 10)
    pdf.rect(14, pdf.get_y(), 182, 8, "F")
    pdf.set_xy(16, pdf.get_y() + 1)
    pdf.cell(0, 6, "Full Conversation Transcript")
    pdf.ln(12)

    pdf.set_text_color(60, 60, 60)
    pdf.set_font(body_font, "", 8)   # NotoSans renders Hindi correctly here
    for line in transcript_lines:
        if line.startswith("Agent") or line.startswith("Patient"):
            pdf.set_x(16)
            # Use multi_cell with unicode font — no clean needed!
            pdf.multi_cell(178, 5, line)

    return bytes(pdf.output())

# ════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════
st.markdown(
    '<div style="background:#2D6A4F;padding:20px 28px;border-radius:10px;margin-bottom:24px;">'
    '<h1 style="color:white;margin:0;font-size:26px;">MediCare Pharmacy</h1>'
    '<p style="color:#a8d5b5;margin:4px 0 0 0;font-size:14px;">AI Patient Follow-up Dashboard</p>'
    '</div>',
    unsafe_allow_html=True
)

patients = load_patients()
total    = len(patients)
due_soon = sum(1 for p in patients.values()
               if get_patient_status(p) in ["DUE SOON","URGENT","OVERDUE"])
reports  = len(get_report_files())

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Patients",    total)
col2.metric("Refills Due",       due_soon)
col3.metric("Reports Generated", reports)
col4.metric("Today",             date.today().strftime("%d %b %Y"))

st.markdown("---")
tab1, tab2, tab3 = st.tabs(["Patients & Calls", "Call History & Reports", "Live AI Call"])

# ════════════════════════════════════════════════
# TAB 1 — PATIENT LIST
# ════════════════════════════════════════════════
with tab1:
    st.subheader("Patient List")
    st.caption("Click Start Call to begin an AI follow-up")

    for pid, patient in patients.items():
        status = get_patient_status(patient)
        col_name, col_drugs, col_refill, col_status, col_btn = st.columns([2.5, 3, 2, 1.5, 1.5])

        with col_name:
            st.markdown("**" + patient["name"] + "**")
            st.caption("Age " + patient["age"] + " | " + patient["language"] + " | " + pid)

        with col_drugs:
            for drug in patient["drugs"]:
                st.caption(drug["drug_name"] + " " + drug["dosage"] + " -- " + drug["frequency"])

        with col_refill:
            for drug in patient["drugs"]:
                days  = days_until_refill(drug["refill_due"])
                color = "red" if days <= 3 else "orange" if days <= 7 else "green"
                st.markdown(
                    '<span style="color:' + color + ';font-size:13px;">'
                    + drug["drug_name"] + ": " + drug["refill_due"]
                    + " (" + str(days) + "d)</span><br>",
                    unsafe_allow_html=True
                )

        with col_status:
            st.markdown(status_badge(status), unsafe_allow_html=True)

        with col_btn:
            if st.button("Start Call", key="call_" + pid):
                st.session_state["active_patient"] = pid
                st.session_state["chat_history"]   = []
                st.session_state["conv_history"]   = []
                st.session_state["call_started"]   = False
                st.session_state["call_ended"]     = False
                st.session_state["transcript"]     = []
                st.session_state["pdf_bytes"]      = None
                st.session_state["pdf_filename"]   = ""
                st.rerun()

        st.markdown("<hr style='margin:8px 0;opacity:0.2;'>", unsafe_allow_html=True)

# ════════════════════════════════════════════════
# TAB 2 — CALL HISTORY
# ════════════════════════════════════════════════
with tab2:
    st.subheader("Call History & Reports")
    report_files     = get_report_files()
    transcript_files = get_transcript_files()

    if not report_files and not transcript_files:
        st.info("No calls completed yet. Start an AI call from the Patients tab!")
    else:
        col_r, col_t = st.columns(2)

        with col_r:
            st.markdown("**PDF Reports**")
            if not report_files:
                st.caption("No reports yet")
            for rf in report_files[:10]:
                with open(FOLDER + "\\" + rf, "rb") as pdf_f:
                    st.download_button(
                        label     = "Download " + rf[:35],
                        data      = pdf_f,
                        file_name = rf,
                        mime      = "application/pdf",
                        key       = "dl_" + rf
                    )

        with col_t:
            st.markdown("**Transcripts**")
            if not transcript_files:
                st.caption("No transcripts yet")
            for tf in transcript_files[:10]:
                with st.expander(tf[:40]):
                    with open(FOLDER + "\\" + tf, encoding="utf-8") as txf:
                        st.text(txf.read())

# ════════════════════════════════════════════════
# TAB 3 — LIVE AI CALL
# ════════════════════════════════════════════════
with tab3:
    active_pid = st.session_state.get("active_patient", None)

    if not active_pid:
        st.info("Go to Patients & Calls tab and click Start Call next to a patient.")
    else:
        patient = patients[active_pid]
        st.subheader("Live Call: " + patient["name"])

        col_info, col_drugs = st.columns([1, 2])
        with col_info:
            st.caption("Age: " + patient["age"] + " | Language: " + patient["language"])
        with col_drugs:
            for drug in patient["drugs"]:
                st.caption(drug["drug_name"] + " " + drug["dosage"] +
                           " -- Refill: " + drug["refill_due"])
        st.markdown("---")

        for key, default in [
            ("chat_history", []), ("conv_history", []),
            ("call_started", False), ("call_ended", False),
            ("transcript", []), ("pdf_bytes", None), ("pdf_filename", "")
        ]:
            if key not in st.session_state:
                st.session_state[key] = default

        context = format_patient_context(patient)
        system_prompt = (
            "You are a warm, caring pharmacy assistant making a follow-up call.\n\n"
            "Patient information:\n" + context + "\n\n"
            "Goals:\n"
            "1. Greet patient warmly by first name\n"
            "2. Ask if taking medications as prescribed\n"
            "3. Check for side effects or discomfort\n"
            "4. Remind about refills due within 7 days\n"
            "5. Ask briefly about general health\n"
            "6. Once all goals covered, close the call warmly\n\n"
            "Rules:\n"
            "- Keep responses to 2-3 sentences\n"
            "- Be warm and simple, not clinical\n"
            "- NEVER suggest dose changes or diagnose\n"
            "- If patient says bye/done/goodbye -> close with [END CALL]\n"
            "- If serious symptoms -> say pharmacist will call back then [END CALL]\n"
            "- Reply in patient preferred language: " + patient["language"]
        )

        if not st.session_state["call_started"]:
            if st.button("Start AI Call", type="primary"):
                st.session_state["conv_history"] = [
                    {"role": "system", "content": system_prompt}
                ]
                response = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=st.session_state["conv_history"] + [
                        {"role": "user", "content": "Start the call with opening greeting only."}
                    ],
                    temperature=0.7,
                    max_tokens=150
                )
                opening = response.choices[0].message.content
                st.session_state["conv_history"].append({"role": "assistant", "content": opening})
                st.session_state["chat_history"].append({"role": "agent", "text": opening})
                st.session_state["transcript"].append("Agent   : " + opening)
                st.session_state["call_started"] = True
                st.rerun()

        if st.session_state["call_started"] and not st.session_state["call_ended"]:
            for msg in st.session_state["chat_history"]:
                if msg["role"] == "agent":
                    with st.chat_message("assistant"):
                        st.write(msg["text"])
                else:
                    with st.chat_message("user"):
                        st.write(msg["text"])

            col_input, col_end = st.columns([4, 1])
            with col_input:
                patient_input = st.chat_input("Type patient reply here...")
            with col_end:
                st.write("")
                end_clicked = st.button("End Call", type="secondary")

            if patient_input:
                st.session_state["chat_history"].append({"role": "patient", "text": patient_input})
                st.session_state["transcript"].append("Patient : " + patient_input)
                st.session_state["conv_history"].append({"role": "user", "content": patient_input})

                if check_serious_symptoms(patient_input):
                    escalation = (
                        "I am very concerned to hear that. "
                        "I am flagging this for our pharmacist "
                        "who will call you back shortly. Please stay safe! [END CALL]"
                    )
                    st.session_state["chat_history"].append({"role": "agent", "text": escalation})
                    st.session_state["transcript"].append("Agent   : " + escalation)
                    st.session_state["call_ended"] = True
                else:
                    response = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=st.session_state["conv_history"],
                        temperature=0.7,
                        max_tokens=150
                    )
                    agent_reply = response.choices[0].message.content
                    st.session_state["conv_history"].append({"role": "assistant", "content": agent_reply})
                    st.session_state["chat_history"].append({"role": "agent", "text": agent_reply})
                    st.session_state["transcript"].append("Agent   : " + agent_reply)
                    if "[END CALL]" in agent_reply:
                        st.session_state["call_ended"] = True
                st.rerun()

            if end_clicked:
                closing = "Thank you " + patient["name"] + "! Stay healthy. Goodbye!"
                st.session_state["chat_history"].append({"role": "agent", "text": closing})
                st.session_state["transcript"].append("Agent   : " + closing)
                st.session_state["call_ended"] = True
                st.rerun()

        if st.session_state["call_ended"]:
            for msg in st.session_state["chat_history"]:
                if msg["role"] == "agent":
                    with st.chat_message("assistant"):
                        st.write(msg["text"])
                else:
                    with st.chat_message("user"):
                        st.write(msg["text"])

            st.markdown("---")
            st.success("Call ended! Generating PDF report...")

            if st.session_state["pdf_bytes"] is None:
                with st.spinner("AI is writing the summary..."):
                    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
                    tx_filename = "transcript_" + active_pid + "_" + timestamp + ".txt"
                    tx_path     = FOLDER + "\\" + tx_filename
                    header = (
                        "\nPATIENT CALL TRANSCRIPT\n" +
                        "=" * 45 + "\n" +
                        "Patient : " + patient["name"] + "\n" +
                        "Date    : " + date.today().strftime("%d %B %Y") + "\n" +
                        "=" * 45 + "\n\n"
                    )
                    with open(tx_path, "w", encoding="utf-8") as f:
                        f.write(header)
                        f.write("\n".join(st.session_state["transcript"]))

                    summary_raw = generate_summary(st.session_state["transcript"], patient)
                    sections    = parse_summary(summary_raw)

                    pdf_filename = "report_" + active_pid + "_" + timestamp + ".pdf"
                    pdf_path     = FOLDER + "\\" + pdf_filename
                    pdf_bytes    = generate_pdf(
                        sections,
                        st.session_state["transcript"],
                        patient["name"],
                        tx_filename
                    )
                    with open(pdf_path, "wb") as f:
                        f.write(pdf_bytes)

                    st.session_state["pdf_bytes"]    = pdf_bytes
                    st.session_state["pdf_filename"] = pdf_filename

            st.markdown("### Report Ready!")
            st.download_button(
                label     = "Download PDF Report",
                data      = st.session_state["pdf_bytes"],
                file_name = st.session_state["pdf_filename"],
                mime      = "application/pdf",
                type      = "primary"
            )

            if st.button("Start New Call"):
                for key in ["active_patient","chat_history","conv_history",
                            "call_started","call_ended","transcript",
                            "pdf_bytes","pdf_filename"]:
                    st.session_state.pop(key, None)
                st.rerun()