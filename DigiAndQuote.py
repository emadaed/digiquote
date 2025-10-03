# digireceipt_final.py
import streamlit as st
from datetime import datetime, timezone
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from PIL import Image
import qrcode
import sqlite3
import pandas as pd
import json

# ------------------ Page Config ------------------
st.set_page_config(page_title="DigiReceipt - Free Invoice and Quote Generator", page_icon="🧾", layout="centered")

# ------------------ Database ------------------
DB_FILE = "digireceipts.db"


def get_conn():
    """Connects to the SQLite database."""
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    """Initializes the database tables if they don't exist and adds missing columns."""
    conn = get_conn()
    c = conn.cursor()

    # Create tables if they don't exist
    c.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            vendor TEXT,
            invoice_no TEXT,
            total REAL,
            user_id TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS invoices_full (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            invoice_no TEXT,
            invoice_json TEXT,
            user_id TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            address TEXT,
            phone TEXT,
            ntn TEXT,
            notes TEXT,
            created_at TEXT
        )
    """)

    # Check and add missing 'user_id' column to 'invoices' table
    c.execute("PRAGMA table_info(invoices)")
    columns = [col[1] for col in c.fetchall()]
    if 'user_id' not in columns:
        c.execute("ALTER TABLE invoices ADD COLUMN user_id TEXT")
        st.info("Database table 'invoices' updated to include 'user_id' column.")

    # Check and add missing 'user_id' column to 'invoices_full' table
    c.execute("PRAGMA table_info(invoices_full)")
    columns = [col[1] for col in c.fetchall()]
    if 'user_id' not in columns:
        c.execute("ALTER TABLE invoices_full ADD COLUMN user_id TEXT")
        c.execute("ALTER TABLE clients ADD COLUMN user_id TEXT")
        st.info("Database table 'invoices_full' and 'clients' updated to include 'user_id' column.")

    conn.commit()
    conn.close()


def log_invoice(timestamp, vendor, invoice_no, total, invoice_json, user_id):
    """Logs the invoice to the database."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO invoices (timestamp, vendor, invoice_no, total, user_id) VALUES (?, ?, ?, ?, ?)",
              (timestamp, vendor, invoice_no, total, user_id))
    c.execute("INSERT INTO INVOICES_FULL (timestamp, invoice_no, invoice_json, user_id) VALUES (?, ?, ?, ?)",
              (timestamp, invoice_no, json.dumps(invoice_json), user_id))
    conn.commit()
    conn.close()


def get_invoices_from_db(user_id):
    """Retrieves all invoices for a specific user from the database."""
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM invoices WHERE user_id = ?", conn, params=(user_id,))
    conn.close()
    return df


def get_last_invoice_no_from_db():
    """Retrieves the last used invoice number from the database."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT invoice_no FROM invoices ORDER BY id DESC LIMIT 1")
    result = c.fetchone()
    conn.close()
    if result:
        try:
            # Assumes invoice number is a simple integer.
            return int(result[0])
        except (ValueError, IndexError):
            # Fallback for non-integer invoice numbers
            return 0
    return 0


def get_full_invoice_data(invoice_no, user_id):
    """Retrieves full invoice data from the database."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT invoice_json FROM invoices_full WHERE invoice_no = ? AND user_id = ?", (invoice_no, user_id))
    result = c.fetchone()
    conn.close()
    if result:
        return json.loads(result[0])
    return None


def generate_pdf(invoice_data, qr_data_str, logo_file=None, language="English", doc_type="invoice"):
    """Generates a POS-style PDF invoice or quote for a 58mm printer."""
    # Use a custom size for a 58mm receipt, with a dynamically growing height
    width = 58 * mm
    height = 297 * mm # Start with a standard height and add pages if needed

    # Translation dictionary for the PDF
    pdf_labels = {
        "English": {
            "invoice_no": "Invoice No:",
            "quote_no": "Quote No:",
            "date": "Date:",
            "description": "Description",
            "total": "Total",
            "subtotal": "Subtotal:",
            "discount": "Discount:",
            "grand_total": "Grand Total:",
            "thank_you_invoice": "Thank you for your business!",
            "thank_you_quote": "We look forward to working with you!",
            "note_invoice": "Note: This is a system-generated receipt and requires no signature.",
            "note_quote": "Note: This is a system-generated quote. Prices are valid for 30 days."
        },
        "Urdu": {
            "invoice_no": "رسید نمبر:",
            "quote_no": "پیداواری قیمت:",
            "date": "تاریخ:",
            "description": "تفصیل",
            "total": "کُل",
            "subtotal": "مجموعی رقم:",
            "discount": "چھوٹ:",
            "grand_total": "کل رقم:",
            "thank_you_invoice": "آپ کے کاروبار کے لئے شکریہ!",
            "thank_you_quote": "ہم آپ کے ساتھ کام کرنے کے منتظر ہیں!",
            "note_invoice": "نوٹ: یہ ایک نظام سے تیار کردہ رسید ہے اور اس پر دستخط کی ضرورت نہیں ہے۔",
            "note_quote": "نوٹ: یہ ایک نظام سے تیار کردہ قیمت ہے۔ قیمتیں 30 دنوں کے لیے درست ہیں۔"
        }
    }
    
    labels = pdf_labels[language]

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))

    # Define fonts and sizes
    c.setFont("Helvetica", 8)

    # Centering helper function
    def center_text(y, text, font="Helvetica", font_size=8, bold=False):
        if bold:
            c.setFont(font + "-Bold", font_size)
        else:
            c.setFont(font, font_size)
        text_width = c.stringWidth(text, font, font_size)
        x_pos = (width - text_width) / 2
        c.drawString(x_pos, height - y * mm, text)

    # Header
    y_offset = 10
    if logo_file:
        try:
            logo_img = Image.open(logo_file)
            logo_width, logo_height = logo_img.size
            aspect_ratio = logo_height / logo_width
            img_width = 40 * mm
            img_height = img_width * aspect_ratio
            x_pos = (width - img_width) / 2
            c.drawImage(ImageReader(logo_img), x_pos, height - y_offset * mm - img_height, width=img_width, height=img_height, preserveAspectRatio=True)
            y_offset += img_height / mm + 5
        except Exception as e:
            st.warning(f"Error loading logo: {e}")

    # Vendor Details (centered)
    vendor_data = invoice_data.get("vendor", {})
    center_text(y_offset, vendor_data.get('name', 'N/A'), font_size=10, bold=True)
    y_offset += 4
    center_text(y_offset, vendor_data.get('address', 'N/A'))
    y_offset += 4
    center_text(y_offset, f"Phone: {vendor_data.get('phone', 'N/A')}")
    y_offset += 4
    center_text(y_offset, f"NTN: {vendor_data.get('ntn', 'N/A')}")
    y_offset += 8

    # Invoice Details (left-aligned)
    invoice_info = invoice_data.get("invoice_info", {})
    if doc_type == "invoice":
        c.drawString(5 * mm, height - y_offset * mm, f"{labels['invoice_no']} {invoice_info.get('invoice_no', 'N/A')}")
    else:
        c.drawString(5 * mm, height - y_offset * mm, f"{labels['quote_no']} {invoice_info.get('invoice_no', 'N/A')}")
    y_offset += 4
    c.drawString(5 * mm, height - y_offset * mm, f"{labels['date']} {invoice_info.get('date', 'N/A')}")
    y_offset += 8

    # Item Table Header
    c.line(5 * mm, height - y_offset * mm, width - 5 * mm, height - y_offset * mm)
    y_offset += 3
    c.setFont("Helvetica-Bold", 8)
    c.drawString(5 * mm, height - y_offset * mm, labels["description"])
    c.drawRightString(width - 5 * mm, height - y_offset * mm, labels["total"])
    c.setFont("Helvetica", 8)
    y_offset += 3
    c.line(5 * mm, height - y_offset * mm, width - 5 * mm, height - y_offset * mm)
    y_offset += 3

    # Item Table
    for item in invoice_data.get("items", []):
        c.drawString(5 * mm, height - y_offset * mm, item.get('name', 'N/A'))
        y_offset += 4
        c.drawString(5 * mm, height - y_offset * mm, f"{item.get('quantity', 0)} x {item.get('price', 0):.2f}")
        c.drawRightString(width - 5 * mm, height - y_offset * mm, f"{item.get('line_total', 0):.2f}")
        y_offset += 5

    y_offset += 3
    c.line(5 * mm, height - y_offset * mm, width - 5 * mm, height - y_offset * mm)
    y_offset += 3

    # Totals
    c.drawString(5 * mm, height - y_offset * mm, labels["subtotal"])
    c.drawRightString(width - 5 * mm, height - y_offset * mm, f"{invoice_data.get('subtotal', 0):.2f}")
    y_offset += 4
    c.drawString(5 * mm, height - y_offset * mm, labels["discount"])
    c.drawRightString(width - 5 * mm, height - y_offset * mm, f"{invoice_data.get('discount', 0):.2f}")
    y_offset += 4
    c.setFont("Helvetica-Bold", 10)
    c.drawString(5 * mm, height - y_offset * mm, labels["grand_total"])
    c.drawRightString(width - 5 * mm, height - y_offset * mm, f"{invoice_data.get('grand_total', 0):.2f}")
    c.setFont("Helvetica", 8)
    y_offset += 8

    # Footer
    if doc_type == "invoice":
        center_text(y_offset, labels["thank_you_invoice"], font_size=8, bold=True)
    else:
        center_text(y_offset, labels["thank_you_quote"], font_size=8, bold=True)
    y_offset += 4

    # QR Code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    qr_buffer = BytesIO()
    img.save(qr_buffer, "PNG")
    qr_buffer.seek(0)
    qr_size = 40 * mm
    qr_x_pos = (width - qr_size) / 2
    c.drawImage(ImageReader(qr_buffer), qr_x_pos, height - y_offset * mm - qr_size, width=qr_size, height=qr_size)
    y_offset += qr_size / mm + 5
    
    if doc_type == "invoice":
        center_text(y_offset, labels["note_invoice"], font_size=6, bold=False)
    else:
        center_text(y_offset, labels["note_quote"], font_size=6, bold=False)
    y_offset += 4

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# Initialize the database here to ensure tables exist before any data access.
init_db()

def app():
    """Main Streamlit application."""
    st.title("🧾 DigiReceipt")

    st.markdown("""
        <div style="background-color:#f0f2f6; padding:10px; border-radius:10px; text-align:center;">
            <p style="font-size:1.2rem; font-weight:bold;">Empowering local communities with simple and accessible tools.</p>
            <p style="font-size:0.9rem;">
                This project is dedicated to helping micro-businesses by providing a simple,
                efficient way to generate invoices. Our goal is to address the pain points
                of people who may not be fluent in English, with a focus on empathy and clarity.
            </p>
            <p style="font-size:0.8rem; color:#6c757d;">
                Note: Language support is a key feature we aim to add in future updates.
            </p>
        </div>
    """, unsafe_allow_html=True)
    st.markdown("---")


    # Language switcher
    language = st.radio("Select Language / زبان کا انتخاب کریں", ("English", "Urdu"), horizontal=True)

    # Translation dictionary for the UI
    ui_labels = {
        "English": {
            "user_id_label": "Enter your User ID (e.g., your shop ID)",
            "user_id_info": "Please enter a User ID to proceed.",
            "create_document_header": "Create New Document",
            "select_doc_type": "Select Document Type",
            "invoice_option": "Invoice",
            "quote_option": "Quote",
            "vendor_details_header": "Vendor Details",
            "vendor_name": "Vendor Name",
            "vendor_address": "Vendor Address",
            "vendor_phone": "Vendor Phone",
            "vendor_ntn": "Vendor NTN",
            "upload_logo": "Upload your logo (optional)",
            "client_details_button": "Show/Hide Client Details",
            "client_details_header": "Client Details (for your records)",
            "client_details_info": "Note: This information is for your personal records and will not appear on the printed receipt.",
            "client_name": "Client Name",
            "client_address": "Client Address",
            "client_phone": "Client Phone",
            "client_ntn": "Client NTN (optional)",
            "notes": "Notes",
            "item_details_header": "Item Details",
            "add_item": "Add Item",
            "remove_item": "Remove Last Item",
            "item_name": "Item Name",
            "quantity": "Quantity",
            "price": "Price",
            "total": "Total:",
            "discount_header": "Discount",
            "discount_amount": "Discount Amount",
            "subtotal": "Subtotal:",
            "grand_total": "Grand Total:",
            "generate_button": "Generate Document",
            "validation_warning": "Please ensure at least one item has a name, quantity, and price.",
            "item_validation_warning": "Item name is filled, but quantity and/or price is empty. Please check your entries.",
            "success_message": "Document {} generated! Grand Total: {:.2f}",
            "download_pdf": "📥 Download PDF",
            "download_csv": "📥 Download Items CSV",
            "past_documents_header": "View Past Documents",
            "load_document_header": "Load a Past Document",
            "load_doc_input": "Enter a document number to load",
            "load_doc_button": "Load Document",
            "load_doc_success": "Document {} loaded. Please make any changes and click Generate to save.",
            "no_documents_found": "No past documents found."
        },
        "Urdu": {
            "user_id_label": "اپنا صارف ID درج کریں (مثلاً اپنی دکان کا ID)",
            "user_id_info": "آگے بڑھنے کے لیے براہ کرم ایک صارف ID درج کریں۔",
            "create_document_header": "نیا دستاویز بنائیں",
            "select_doc_type": "دستاویز کی قسم منتخب کریں",
            "invoice_option": "رسید",
            "quote_option": "اقتباس",
            "vendor_details_header": "دکاندار کی تفصیلات",
            "vendor_name": "دکاندار کا نام",
            "vendor_address": "دکاندار کا پتہ",
            "vendor_phone": "دکاندار کا فون نمبر",
            "vendor_ntn": "دکاندار کا NTN",
            "upload_logo": "اپنا لوگو اپ لوڈ کریں (اختیاری)",
            "client_details_button": "گاہک کی تفصیلات دکھائیں/چھپائیں",
            "client_details_header": "گاہک کی تفصیلات (آپ کے ریکارڈ کے لیے)",
            "client_details_info": "نوٹ: یہ معلومات آپ کے ذاتی ریکارڈ کے لیے ہے اور پرنٹ شدہ رسید پر ظاہر نہیں ہوگی۔",
            "client_name": "گاہک کا نام",
            "client_address": "گاہک کا پتہ",
            "client_phone": "گاہک کا فون نمبر",
            "client_ntn": "گاہک کا NTN (اختیاری)",
            "notes": "نوٹ",
            "item_details_header": "اشیاء کی تفصیلات",
            "add_item": "آئٹم شامل کریں",
            "remove_item": "آخری آئٹم ہٹائیں",
            "item_name": "آئٹم کا نام",
            "quantity": "تعداد",
            "price": "قیمت",
            "total": "کُل:",
            "discount_header": "چھوٹ",
            "discount_amount": "چھوٹ کی رقم",
            "subtotal": "مجموعی رقم:",
            "grand_total": "کل رقم:",
            "generate_button": "دستاویز بنائیں",
            "validation_warning": "براہ کرم یقینی بنائیں کہ کم از کم ایک آئٹم کا نام، تعداد، اور قیمت درج کی گئی ہے۔",
            "item_validation_warning": "آئٹم کا نام بھرا ہوا ہے، لیکن مقدار اور/یا قیمت خالی ہے۔ براہ کرم اپنی اندراجات کی جانچ کریں۔",
            "success_message": "دستاویز {} بنایا گیا! کل رقم: {:.2f}",
            "download_pdf": "📥 پی ڈی ایف ڈاؤن لوڈ کریں",
            "download_csv": "📥 اشیاء کی CSV ڈاؤن لوڈ کریں",
            "past_documents_header": "گزشتہ دستاویزات دیکھیں",
            "load_document_header": "گزشتہ دستاویز لوڈ کریں",
            "load_doc_input": "لوڈ کرنے کے لیے دستاویز نمبر درج کریں",
            "load_doc_button": "دستاویز لوڈ کریں",
            "load_doc_success": "دستاویز {} لوڈ کیا گیا ہے۔ براہ کرم کوئی بھی تبدیلی کریں اور محفوظ کرنے کے لیے بنائیں پر کلک کریں۔",
            "no_documents_found": "کوئی گزشتہ دستاویز نہیں ملا۔"
        }
    }
    
    labels = ui_labels[language]


    # Add a user ID input field
    st.session_state["user_id"] = st.text_input(labels["user_id_label"], key="user_id_input")

    if not st.session_state["user_id"]:
        st.info(labels["user_id_info"])
        st.stop()

    # Handle URL parameter for loading an invoice
    query_params = st.query_params
    if 'invoice_no' in query_params and 'loaded' not in st.session_state:
        invoice_no_to_load = query_params['invoice_no']
        loaded_data = get_full_invoice_data(invoice_no_to_load, st.session_state["user_id"])
        if loaded_data:
            st.session_state["invoice_data"] = loaded_data
            st.success(labels["load_doc_success"].format(invoice_no_to_load))
            st.session_state["loaded"] = True
        else:
            st.error("Could not find that document.")

    # Initialize session state variables
    if "invoice_data" not in st.session_state:
        st.session_state["invoice_data"] = {
            "vendor": {"name": "", "address": "", "phone": "", "ntn": ""},
            "client": {"name": "", "address": "", "phone": "", "ntn": "", "notes": ""},
            # Initialized with one item to prevent StreamlitValueBelowMinError
            "items": [{"name": "", "quantity": 1, "price": 0.0}],
            "doc_type": "invoice" # Default to invoice
        }
    if "show_client_details" not in st.session_state:
        st.session_state["show_client_details"] = False
    
    st.header(labels["create_document_header"])
    
    # Select document type (Invoice or Quote)
    st.session_state["invoice_data"]["doc_type"] = st.radio(
        labels["select_doc_type"],
        (labels["invoice_option"], labels["quote_option"]),
        horizontal=True
    ).lower()

    # This button must be outside the form to avoid the StreamlitAPIException.
    client_button = st.button(labels["client_details_button"])
    if client_button:
        st.session_state["show_client_details"] = not st.session_state["show_client_details"]

    with st.form(key='invoice_form'):
        st.subheader(labels["vendor_details_header"])
        st.session_state["invoice_data"]["vendor"]["name"] = st.text_input(labels["vendor_name"], st.session_state["invoice_data"]["vendor"]["name"])
        st.session_state["invoice_data"]["vendor"]["address"] = st.text_input(labels["vendor_address"], st.session_state["invoice_data"]["vendor"]["address"])
        st.session_state["invoice_data"]["vendor"]["phone"] = st.text_input(labels["vendor_phone"], st.session_state["invoice_data"]["vendor"]["phone"])
        st.session_state["invoice_data"]["vendor"]["ntn"] = st.text_input(labels["vendor_ntn"], st.session_state["invoice_data"]["vendor"]["ntn"])
        logo_file = st.file_uploader(labels["upload_logo"], type=["png", "jpg", "jpeg"])

        if st.session_state["show_client_details"]:
            st.subheader(labels["client_details_header"])
            st.info(labels["client_details_info"])
            st.session_state["invoice_data"]["client"]["name"] = st.text_input(labels["client_name"], st.session_state["invoice_data"]["client"]["name"])
            st.session_state["invoice_data"]["client"]["address"] = st.text_input(labels["client_address"], st.session_state["invoice_data"]["client"]["address"])
            st.session_state["invoice_data"]["client"]["phone"] = st.text_input(labels["client_phone"], st.session_state["invoice_data"]["client"]["phone"])
            st.session_state["invoice_data"]["client"]["ntn"] = st.text_input(labels["client_ntn"], st.session_state["invoice_data"]["client"]["ntn"])
            st.session_state["invoice_data"]["client"]["notes"] = st.text_area(labels["notes"], st.session_state["invoice_data"]["client"]["notes"])


        st.subheader(labels["item_details_header"])
        
        # Dynamic Add/Remove Item Buttons
        add_item_button = st.form_submit_button(labels["add_item"])
        if add_item_button:
            st.session_state["invoice_data"]["items"].append({"name": "", "quantity": 1, "price": 0.0})
        
        if len(st.session_state["invoice_data"]["items"]) > 1:
            remove_item_button = st.form_submit_button(labels["remove_item"])
            if remove_item_button:
                st.session_state["invoice_data"]["items"].pop()
        
        subtotal = 0
        for i, item in enumerate(st.session_state["invoice_data"]["items"]):
            st.markdown(f"**Item #{i+1}**")
            cols = st.columns([3, 1, 1, 1])
            with cols[0]:
                st.session_state["invoice_data"]["items"][i]["name"] = st.text_input(labels["item_name"], item["name"], key=f"item_name_{i}")
            with cols[1]:
                st.session_state["invoice_data"]["items"][i]["quantity"] = st.number_input(labels["quantity"], min_value=1, value=item["quantity"], key=f"item_quantity_{i}")
            with cols[2]:
                st.session_state["invoice_data"]["items"][i]["price"] = st.number_input(labels["price"], min_value=0.0, value=item["price"], step=0.01, key=f"item_price_{i}")
            with cols[3]:
                line_total = item["quantity"] * item["price"]
                st.markdown(f"**{labels['total']}** {line_total:.2f}")
                item["line_total"] = line_total
            subtotal += line_total

        st.subheader(labels["discount_header"])
        discount_amount = st.number_input(labels["discount_amount"], min_value=0.0, value=0.0, step=0.01)

        st.markdown(f"**{labels['subtotal']}** {subtotal:.2f}")
        st.markdown(f"**{labels['grand_total']}** {(subtotal - discount_amount):.2f}")

        generate_button = st.form_submit_button(labels["generate_button"])

    if generate_button:
        # Check for incomplete items
        incomplete_item_exists = False
        for item in st.session_state["invoice_data"]["items"]:
            if item.get("name") and (item.get("quantity", 0) <= 0 or item.get("price", 0) <= 0):
                st.warning(labels["item_validation_warning"])
                incomplete_item_exists = True
                break
        
        if incomplete_item_exists:
            # Clear download state on failed attempt
            if "last_invoice_info" in st.session_state:
                del st.session_state["last_invoice_info"]
            st.stop()
        
        # Check if any item has valid data (name, quantity, and price > 0)
        is_valid_items = any(
            item.get("name") and item.get("quantity", 0) > 0 and item.get("price", 0) > 0
            for item in st.session_state["invoice_data"]["items"]
        )

        grand_total = subtotal - discount_amount

        # Only proceed with invoice generation if validation passes
        if not is_valid_items:
            st.warning(labels["validation_warning"])
            # Clear download state on failed attempt
            if "last_invoice_info" in st.session_state:
                del st.session_state["last_invoice_info"]
        else:
            # Generate the new invoice number
            last_invoice_no = get_last_invoice_no_from_db()
            invoice_no = f"{last_invoice_no + 1:04d}"
            
            timestamp = datetime.now(timezone.utc).isoformat()

            # Build the complete invoice data dictionary
            invoice_data = st.session_state["invoice_data"]
            invoice_data["invoice_info"] = {
                "invoice_no": invoice_no,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "timestamp": timestamp,
            }
            invoice_data["subtotal"] = subtotal
            invoice_data["discount"] = discount_amount
            invoice_data["grand_total"] = grand_total

            # Save the full invoice JSON to the database
            log_invoice(timestamp, invoice_data["vendor"]["name"], invoice_no, grand_total, invoice_data, st.session_state["user_id"])

            st.success(labels["success_message"].format(invoice_no, grand_total))
            
            # Retrieve the invoice data from the database to ensure QR code has complete information
            full_invoice_data = get_full_invoice_data(invoice_no, st.session_state["user_id"])
            if full_invoice_data:
                qr_data_str = json.dumps(full_invoice_data, indent=2)
            else:
                qr_data_str = "Error retrieving invoice data."

            # Generate PDF with the full QR data
            pdf_buffer = generate_pdf(invoice_data, qr_data_str, logo_file=logo_file, language=language, doc_type=st.session_state["invoice_data"]["doc_type"])

            try:
                items_df = pd.DataFrame(invoice_data.get("items", []))
                csv_bytes = items_df.to_csv(index=False).encode("utf-8")
            except Exception:
                csv_bytes = None
            
            # Store the generated data in session state for the download buttons
            st.session_state["last_invoice_info"] = {
                "pdf_buffer": pdf_buffer,
                "invoice_no": invoice_no,
                "csv_bytes": csv_bytes,
            }

    # ------------------ OUTSIDE THE FORM (download buttons are here) ------------------
    if "last_invoice_info" in st.session_state:
        info = st.session_state["last_invoice_info"]
        st.download_button(
            labels["download_pdf"],
            info["pdf_buffer"],
            file_name=f"{info['invoice_no']}.pdf",
            mime="application/pdf"
        )
        if info["csv_bytes"] is not None:
            st.download_button(
                labels["download_csv"],
                info["csv_bytes"],
                file_name=f"{info['invoice_no']}_items.csv",
                mime="text/csv"
            )

    # ------------------ Past Invoices Section ------------------
    st.header(labels["past_documents_header"])
    
    # Load past document section
    st.subheader(labels["load_document_header"])
    col1, col2 = st.columns([3, 1])
    with col1:
        load_invoice_no = st.text_input(labels["load_doc_input"])
    with col2:
        st.markdown("<br>", unsafe_allow_html=True) # Add some spacing
        load_button = st.button(labels["load_doc_button"])

    if load_button and load_invoice_no:
        loaded_data = get_full_invoice_data(load_invoice_no, st.session_state["user_id"])
        if loaded_data:
            st.session_state["invoice_data"] = loaded_data
            st.success(labels["load_doc_success"].format(load_invoice_no))
            st.rerun()
        else:
            st.error("Could not find that document.")

    # Now pass the user_id to filter the invoices
    invoices_df = get_invoices_from_db(st.session_state.get("user_id", "default_user"))
    if not invoices_df.empty:
        st.dataframe(invoices_df)
    else:
        st.info(labels["no_documents_found"])


if __name__ == "__main__":
    app()
