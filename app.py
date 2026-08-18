import streamlit as st
import pandas as pd
import sqlite3
import openai
import hashlib
import json
from datetime import datetime
import io

# ==========================================
# 1. DATABASE & INITIALIZATION
# ==========================================
DB_FILE = "b2b_database.db"

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Create Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT, is_approved INTEGER DEFAULT 0)''')
    
    # Create Products Table
    c.execute('''CREATE TABLE IF NOT EXISTS products 
                 (id INTEGER PRIMARY KEY, name TEXT, description TEXT, price_aud REAL, image_url TEXT, link_url TEXT)''')
    
    # Create Quotes Table
    c.execute('''CREATE TABLE IF NOT EXISTS quotes 
                 (id INTEGER PRIMARY KEY, customer_id INTEGER, items TEXT, status TEXT, created_at TEXT)''')
                 
    # Create default Admin if not exists (Password: admin123)
    admin_pass = hashlib.sha256("admin123".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username, password, role, is_approved) VALUES (?, ?, ?, ?)", 
              ("admin", admin_pass, "admin", 1))
    
    conn.commit()
    conn.close()

init_db()

# ==========================================
# 2. AI GENERATION FUNCTION
# ==========================================
def generate_ai_description(product_name):
    api_key = st.session_state.get("api_key", "")
    if not api_key:
        return "⚠️ Please add your AI API Key in the sidebar."
    
    try:
        client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": f"Write a professional 2-sentence B2B wholesale description for: {product_name}. Tone: Australian business, reliable, bulk-order friendly."}],
            max_tokens=150
        )
        return response.choices[0].message.content
    except Exception as e:
        return f" AI Error: {str(e)}"

# ==========================================
# 3. AUTHENTICATION & SESSION STATE
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.cart = []

def login(username, password):
    conn = get_db()
    pass_hash = hashlib.sha256(password.encode()).hexdigest()
    user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, pass_hash)).fetchone()
    conn.close()
    if user:
        st.session_state.logged_in = True
        st.session_state.user = dict(user)
        return True
    return False

def logout():
    st.session_state.logged_in = False
    st.session_state.user = None
    st.session_state.cart = []

# ==========================================
# 4. MAIN APP UI
# ==========================================
st.set_page_config(page_title="🇦 AU B2B Wholesale Portal", layout="wide")

# --- SIDEBAR: API KEY & LOGIN ---
with st.sidebar:
    st.title("🇦🇺 AU B2B Portal")
    
    if not st.session_state.logged_in:
        st.header("🔐 Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login", use_container_width=True):
            if login(username, password):
                st.rerun()
            else:
                st.error("Invalid credentials or account not approved.")
        
        st.markdown("---")
        st.info("**Default Admin Login:**\nUser: `admin`\nPass: `admin123`")
    else:
        st.success(f"Logged in as: **{st.session_state.user['username']}** ({st.session_state.user['role']})")
        if st.button("Logout", use_container_width=True):
            logout()
            st.rerun()
            
        st.markdown("---")
        st.subheader("⚙️ AI Settings")
        st.session_state.api_key = st.text_input("DeepSeek API Key", type="password", value=st.session_state.get("api_key", ""))
        st.session_state.markup = st.number_input("Markup (%)", value=30)
        st.session_state.gst = st.number_input("GST (%)", value=10)
        st.session_state.exchange_rate = st.number_input("CNY to AUD Rate", value=4.75)

# --- MAIN CONTENT ---
if not st.session_state.logged_in:
    st.title("Welcome to the AU B2B Wholesale Portal")
    st.info("Please log in via the sidebar to access the portal.")
    
elif st.session_state.user["role"] == "admin":
    # ================= ADMIN DASHBOARD =================
    st.title("️ Admin Dashboard")
    tab1, tab2, tab3, tab4 = st.tabs(["📦 Import 1688 CSV", "🛍️ Products", "👥 Customers", "📝 Quotes"])
    
    with tab1:
        st.header("Import 1688 CSV & Generate AI Content")
        uploaded_file = st.file_uploader("Upload 后羿采集器 CSV", type="csv")
        if uploaded_file:
            df = pd.read_csv(uploaded_file)
            st.write("Preview:", df.head())
            
            if st.button("🚀 Process & Import to Database", type="primary"):
                if "标题" not in df.columns:
                    st.error("CSV must have a '标题' column.")
                else:
                    progress = st.progress(0)
                    conn = get_db()
                    for i, row in df.iterrows():
                        name = str(row["标题"])
                        desc = generate_ai_description(name)
                        try:
                            cost_cny = float(str(row["offer-price"]).replace(',', ''))
                            price_aud = round((cost_cny / st.session_state.exchange_rate) * (1 + st.session_state.markup/100) * (1 + st.session_state.gst/100), 2)
                        except: price_aud = 0.0
                        
                        img = row.get("offer-img", "")
                        link = row.get("标题链接", "")
                        
                        conn.execute("INSERT INTO products (name, description, price_aud, image_url, link_url) VALUES (?,?,?,?,?)",
                                     (name, desc, price_aud, img, link))
                        progress.progress((i + 1) / len(df))
                    
                    conn.commit()
                    conn.close()
                    st.success(f"Successfully imported {len(df)} products!")
                    st.rerun()

    with tab2:
        st.header("Product Catalog")
        conn = get_db()
        products = conn.execute("SELECT * FROM products").fetchall()
        conn.close()
        st.dataframe(pd.DataFrame(products), use_container_width=True)

    with tab3:
        st.header("Customer Approvals")
        conn = get_db()
        customers = conn.execute("SELECT * FROM users WHERE role='customer'").fetchall()
        conn.close()
        for c in customers:
            col1, col2, col3 = st.columns([3, 1, 1])
            col1.write(f"**{c['username']}** - {'✅ Approved' if c['is_approved'] else '⏳ Pending'}")
            if not c['is_approved']:
                if col2.button("Approve", key=f"app_{c['id']}"):
                    conn = get_db()
                    conn.execute("UPDATE users SET is_approved=1 WHERE id=?", (c['id'],))
                    conn.commit()
                    conn.close()
                    st.rerun()

    with tab4:
        st.header("Incoming Quote Requests")
        conn = get_db()
        quotes = conn.execute("SELECT * FROM quotes ORDER BY id DESC").fetchall()
        conn.close()
        for q in quotes:
            st.markdown(f"**Quote #{q['id']}** | Status: {q['status']} | Date: {q['created_at']}")
            st.json(json.loads(q['items']))
            st.divider()

elif st.session_state.user["role"] == "customer":
    # ================= CUSTOMER PORTAL =================
    if not st.session_state.user["is_approved"]:
        st.error(" Your account is pending admin approval. Please check back later.")
        st.stop()

    st.title("🛍️ Customer Wholesale Catalog")
    tab_c1, tab_c2 = st.tabs(["🛒 Product Catalog", "📝 My Quote Cart"])
    
    with tab_c1:
        conn = get_db()
        products = conn.execute("SELECT * FROM products").fetchall()
        conn.close()
        
        cols = st.columns(3)
        for i, p in enumerate(products):
            with cols[i % 3]:
                st.image(p['image_url'], width=200)
                st.subheader(p['name'][:50])
                st.write(f"**Wholesale Price:** ${p['price_aud']:.2f} AUD")
                st.write(p['description'][:100] + "...")
                if st.button("Add to Quote", key=f"cart_{p['id']}"):
                    st.session_state.cart.append(dict(p))
                    st.toast(f"Added {p['name'][:20]} to cart!")

    with tab_c2:
        st.header("Your Quote Request")
        if not st.session_state.cart:
            st.info("Your cart is empty.")
        else:
            total = sum(item['price_aud'] for item in st.session_state.cart)
            st.write(f"**Items in Quote:** {len(st.session_state.cart)}")
            st.write(f"**Estimated Total:** ${total:.2f} AUD")
            
            if st.button("📩 Submit Quote Request to Admin", type="primary"):
                conn = get_db()
                items_json = json.dumps([{"id": i['id'], "name": i['name'], "price": i['price_aud']} for i in st.session_state.cart])
                conn.execute("INSERT INTO quotes (customer_id, items, status, created_at) VALUES (?,?,?,?)",
                             (st.session_state.user['id'], items_json, "Pending", datetime.now().strftime("%Y-%m-%d %H:%M")))
                conn.commit()
                conn.close()
                st.session_state.cart = []
                st.success("Quote submitted successfully! The admin will review it shortly.")
                st.rerun()