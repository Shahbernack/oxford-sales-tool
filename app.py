import streamlit as st
import feedparser
import openai
import pyperclip
import datetime
from email.utils import parsedate_to_datetime
import streamlit_authenticator as stauth
import sqlite3
import pandas as pd

# --- Secrets & OpenAI Key ---
PASSWORD = st.secrets["PASSWORD"]
openai.api_key = st.secrets["OPENAI_API_KEY"]

# --- SQLite für Tracking ---
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

# --- Authenticator Credentials aus Secrets ---
credentials = {
    "usernames": {
        user: {"name": info["name"], "password": info["password"]}
        for user, info in st.secrets["credentials"]["usernames"].items()
    }
}

authenticator = stauth.Authenticate(
    credentials,
    cookie_name="oxford_sales_tool",
    key="oxford_signature",
    cookie_expiry_days=1
)

# --- Login (Location as keyword!) ---
name, auth_status, username = authenticator.login("Login", location="sidebar")
if not auth_status:
    st.stop()

authenticator.logout("Logout", "sidebar")
st.sidebar.write(f"Logged in as: {name}")

# --- Sidebar Statistik ---
stats_df = pd.read_sql_query(
    "SELECT used, COUNT(*) AS count FROM outreach WHERE user = ? GROUP BY used",
    conn, params=(name,)
)
if not stats_df.empty:
    stats_df = stats_df.set_index('used').reindex([0,1], fill_value=0)
    st.sidebar.bar_chart(stats_df['count'], use_container_width=True)
    succ = c.execute(
        "SELECT COUNT(*) FROM outreach WHERE user=? AND success=1",
        (name,)
    ).fetchone()[0]
    total = stats_df.loc[1, 'count']
    rate = f"{succ}/{total} ({succ/total:.0%})" if total > 0 else "N/A"
    st.sidebar.write("Success rate:", rate)

# --- UI ---
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

# --- Fetch & filter news (last 7 days) ---
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
                pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc) if pub_dt.tzinfo is None else pub_dt.astimezone(datetime.timezone.utc)
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
score_impact     = lambda t: openai_chat(f"Rate impact 1-5: '{t}'. Reply number.")
generate_subject = lambda t: openai_chat(f"Write a 6-8 word subject for: '{t}'.")
generate_email   = lambda t,p: openai_chat(f"Persona: {p}\nHeadline: {t}\nWrite concise sales email.", temp=0.7)

# --- Main Loop ---
if st.button("🔍 Fetch & Analyze"):
    raw = fetch_recent_news(keywords_by_sector[sector])
    if not raw:
        st.warning("No news from the last week.")
    else:
        with st.expander("Raw fetched news"):
            for i, item in enumerate(raw):
                st.write(item)

        filtered = filter_news_with_gpt(raw)
        if not filtered:
            st.warning("GPT found no relevant news.")
        else:
            for i, row in enumerate(filtered.split("\n")):
                if "|" not in row:
                    continue
                title, link, pubDate = [p.strip() for p in row.split("|", 3)][:3]
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
                        (name, title)
                    )
                    conn.commit()
                    st.success("Marked as used")
                if col2.button("✔️ Success", key=f"succ_{i}"):
                    c.execute(
                        "UPDATE outreach SET success=1 WHERE user=? AND title=? ORDER BY ts DESC LIMIT 1",
                        (name, title)
                    )
                    conn.commit()
                    st.success("Marked success")
                if col3.button("❌ Fail", key=f"fail_{i}"):
                    c.execute(
                        "UPDATE outreach SET success=0 WHERE user=? AND title=? ORDER BY ts DESC LIMIT 1",
                        (name, title)
                    )
                    conn.commit()
                    st.error("Marked fail")
