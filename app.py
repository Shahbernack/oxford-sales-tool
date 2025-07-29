import streamlit as st
import feedparser
import openai
import pyperclip
import datetime
from email.utils import parsedate_to_datetime
import sqlite3
import pandas as pd

# --- Secrets & OpenAI Key ---
PASSWORD = st.secrets["PASSWORD"]               # e.g. "OETool2025&"
openai.api_key = st.secrets["OPENAI_API_KEY"]

# --- Load all users from Secrets (including guest, Shah, Marvin, Janis, etc.) ---
users = dict(st.secrets["credentials"]["usernames"])

# --- Session State for Auth + Data Persistence ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "raw_news" not in st.session_state:
    st.session_state.raw_news = []
if "filtered_news" not in st.session_state:
    st.session_state.filtered_news = ""

# --- Sidebar Login / Logout ---
with st.sidebar:
    if not st.session_state.authenticated:
        st.header("Login")
        uname = st.text_input("Username")
        pwd   = st.text_input("Password", type="password")
        if st.button("Login"):
            if uname in users and pwd == users[uname]["password"]:
                st.session_state.authenticated = True
                st.session_state.username = uname
            else:
                st.error("Invalid credentials")
        st.stop()
    else:
        st.write(f"Logged in as **{users[st.session_state.username]['name']}**")
        if st.button("Logout"):
            st.session_state.authenticated = False
            st.experimental_rerun()

# --- SQLite for Tracking ---
conn = sqlite3.connect('outreach.db', check_same_thread=False)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS outreach (
  id INTEGER PRIMARY KEY,
  user TEXT,
  title TEXT,
  ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  used INTEGER,
  success INTEGER
)
""")
conn.commit()

# --- Sidebar Statistics ---
stats_df = pd.read_sql_query(
    "SELECT used, COUNT(*) AS count FROM outreach WHERE user = ? GROUP BY used",
    conn, params=(st.session_state.username,)
)
if not stats_df.empty:
    stats_df = stats_df.set_index('used').reindex([0,1], fill_value=0)
    st.sidebar.bar_chart(stats_df['count'], use_container_width=True)
    succ = c.execute(
        "SELECT COUNT(*) FROM outreach WHERE user=? AND success=1",
        (st.session_state.username,)
    ).fetchone()[0]
    total = int(stats_df.loc[1, 'count'])
    rate = f"{succ}/{total} ({succ/total:.0%})" if total > 0 else "N/A"
    st.sidebar.write("Success rate:", rate)

# --- Main UI ---
st.title("Oxford Economics – Sales Email Tool")
sector = st.selectbox("Select a sector", [
    "Professional Services, Government, B2C & Tourism",
    "Real Estate",
    "Asset Management & Financial Services",
    "B2B Manufacturing & Logistics"
])

keywords_by_sector = {
    "Professional Services, Government, B2C & Tourism": ["services","government","tourism","retail","public policy"],
    "Real Estate": ["real estate","property","construction","buildings"],
    "Asset Management & Financial Services": ["finance","banking","asset management","investment","markets"],
    "B2B Manufacturing & Logistics": ["manufacturing","logistics","supply chain","industrial","infrastructure","DACH"]
}

# --- Fetch & Filter Functions ---
def fetch_recent_news(keywords):
    q = "+".join(kw.replace(" ","+") for kw in keywords)
    feeds = [
        f"https://news.google.com/rss/search?q={q}",
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.reuters.com/reuters/worldNews",
        "https://www.bloomberg.com/feed/podcast/bloomberg-surveillance.xml",
        f"https://www.bing.com/news/search?q={q}&format=rss",
        "https://www.ft.com/news-feed?format=rss"
    ]
    one_week_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    entries, seen = [], set()
    for url in feeds:
        for e in feedparser.parse(url).entries:
            try:
                pub_dt = parsedate_to_datetime(e.get("published",""))
                pub_dt = (pub_dt.replace(tzinfo=datetime.timezone.utc)
                          if pub_dt.tzinfo is None
                          else pub_dt.astimezone(datetime.timezone.utc))
            except:
                continue
            if pub_dt < one_week_ago:
                continue
            link = e.get("link","")
            if link in seen:
                continue
            seen.add(link)
            entries.append(f"{e.get('title','')} | {link} | {e.get('published','')}")
            if len(entries) >= 20:
                break
    return entries

def openai_chat(prompt, model="gpt-3.5-turbo", temp=0.2):
    r = openai.chat.completions.create(
        model=model,
        messages=[{"role":"user","content":prompt}],
        temperature=temp
    )
    return r.choices[0].message.content.strip()

def filter_news_with_gpt(news_list):
    h = "\n".join(news_list)
    prompt = f"""You are a research assistant for Sales at Oxford Economics.
From these headlines, return only B2B-relevant items for European companies in {sector}.
Output as Title | Link | pubDate | Region, sorted newest first:

{h}
"""
    return openai_chat(prompt)

assign_persona   = lambda t: openai_chat(f"Given headline: '{t}', list one relevant persona.")
score_impact     = lambda t: openai_chat(f"Rate impact 1-5: '{t}'. Reply with only the number.")
generate_subject = lambda t: openai_chat(f"Write a 6-8 word subject line for: '{t}'.")
generate_email   = lambda t,p: openai_chat(f"Persona: {p}\nHeadline: {t}\nWrite a concise outreach email.", temp=0.7)

# --- Fetch & Analyze Button ---
if st.button("🔍 Fetch & Analyze"):
    st.session_state.raw_news = fetch_recent_news(keywords_by_sector[sector])
    if st.session_state.raw_news:
        st.session_state.filtered_news = filter_news_with_gpt(st.session_state.raw_news)
    else:
        st.session_state.filtered_news = ""

# --- Display Raw News ---
if st.session_state.raw_news:
    with st.expander("Raw fetched news"):
        for item in st.session_state.raw_news:
            st.write(item)

# --- Display Filtered & Email Workflow ---
if st.session_state.filtered_news:
    for i, row in enumerate(st.session_state.filtered_news.split("\n")):
        if "|" not in row:
            continue
        title, link, pubDate = [p.strip() for p in row.split("|",3)][:3]
        st.markdown(f"### {i+1}. [{title}]({link})")
        st.markdown(f"🗓️ {pubDate}")

        persona = assign_persona(title)
        impact  = score_impact(title)
        subject = generate_subject(title)
        email   = generate_email(title, persona)

        st.write(f"**Impact:** {impact}/5  |  **Persona:** {persona}")
        st.text_input("Subject", subject, key=f"subj_{i}")
        st.text_area("Email draft", email, height=200, key=f"email_{i}")

        col1, col2, col3 = st.columns(3)
        if col1.button("Mark as Used", key=f"used_{i}"):
            c.execute(
                "INSERT INTO outreach(user,title,used) VALUES (?,?,1)",
                (st.session_state.username, title)
            )
            conn.commit()
            st.success("Marked as used")
        if col2.button("✔️ Success", key=f"succ_{i}"):
            c.execute(
                "UPDATE outreach SET success=1 WHERE user=? AND title=? ORDER BY ts DESC LIMIT 1",
                (st.session_state.username, title)
            )
            conn.commit()
            st.success("Marked success")
        if col3.button("❌ Fail", key=f"fail_{i}"):
            c.execute(
                "UPDATE outreach SET success=0 WHERE user=? AND title=? ORDER BY ts DESC LIMIT 1",
                (st.session_state.username, title)
            )
            conn.commit()
            st.error("Marked fail")
