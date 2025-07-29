import streamlit as st
import feedparser
import openai
import pyperclip
import datetime
from email.utils import parsedate_to_datetime
import streamlit_authenticator as stauth

# --- Access protection & API key from Secrets ---
PASSWORD = st.secrets["PASSWORD"]
openai.api_key = st.secrets["OPENAI_API_KEY"]
# Build credentials dict from secrets
credentials = {
    "usernames": {
        user: {"name": info["name"], "password": info["password"]}
        for user, info in st.secrets["credentials"]["usernames"].items()
    }
}

# --- Authentication ---
authenticator = stauth.Authenticate(
    credentials,
    cookie_name="oxford_sales_tool",
    key="oxford_signature",
    cookie_expiry_days=1
)
name, auth_status, username = authenticator.login("Login", location="main")

if auth_status is False:
    st.error("Username/password is incorrect")
    st.stop()
elif auth_status is None:
    st.warning("Please enter your credentials")
    st.stop()

# Logout button & show user
authenticator.logout("Logout", "sidebar")
st.sidebar.write(f"Logged in as: {name}")

# --- UI ---
st.title("Oxford Economics – Sales Email Tool")
sector = st.selectbox("Select a sector", [
    "Professional Services, Government, B2C & Tourism",
    "Real Estate",
    "Asset Management & Financial Services",
    "B2B Manufacturing & Logistics"
])

# --- Keywords for each sector ---
keywords_by_sector = {
    "Professional Services, Government, B2C & Tourism": ["services", "government", "tourism", "retail", "public policy"],
    "Real Estate": ["real estate", "property", "construction", "buildings"],
    "Asset Management & Financial Services": ["finance", "banking", "asset management", "investment", "markets"],
    "B2B Manufacturing & Logistics": ["manufacturing", "logistics", "supply chain", "industrial", "infrastructure", "DACH"]
}

# --- Fetch news from RSS and keep only last 7 days ---
def fetch_recent_news(keywords):
    encoded = [kw.replace(" ", "+") for kw in keywords]
    query = "+".join(encoded)
    feeds = [
        f"https://news.google.com/rss/search?q={query}",
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.reuters.com/reuters/worldNews",
        "https://www.bloomberg.com/feed/podcast/bloomberg-surveillance.xml",
        f"https://www.bing.com/news/search?q={query}&format=rss",
        "https://www.ft.com/news-feed?format=rss"
    ]
    one_week_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    entries, seen = [], set()

    for url in feeds:
        feed = feedparser.parse(url)
        for e in feed.entries:
            try:
                pub_dt = parsedate_to_datetime(e.get("published", ""))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
                else:
                    pub_dt = pub_dt.astimezone(datetime.timezone.utc)
            except Exception:
                continue
            if pub_dt < one_week_ago:
                continue

            link = e.get("link", "")
            if link in seen:
                continue
            seen.add(link)

            title = e.get("title", "")
            pub_str = e.get("published", "")
            entries.append(f"{title} | {link} | {pub_str}")
            if len(entries) >= 20:
                break
    return entries

# --- GPT helper ---
def openai_chat(prompt, model="gpt-3.5-turbo", temp=0.2):
    resp = openai.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temp
    )
    return resp.choices[0].message.content.strip()

# --- GPT: Filter relevant articles ---
def filter_news_with_gpt(news_list):
    headlines = "\n".join(news_list)
    prompt = f"""You are a research assistant for Sales at Oxford Economics.
From this list of headlines (Title | Link | pubDate), return only those that are clearly B2B-relevant to European companies in the selected sector or relevant macro topics (tariffs, trade policy, supply-chain risk).
Prioritize Bloomberg, Reuters, and FT content.

Output each item as: Title | Link | pubDate | Region, one per line, sorted newest first:

{headlines}
"""
    return openai_chat(prompt)

# --- GPT: Assign persona, score impact, generate subject & email ---
assign_persona   = lambda t: openai_chat(f"Given this headline: '{t}', list the single most relevant persona (job title) to target.")
score_impact    = lambda t: openai_chat(f"On a scale of 1–5, where 5 = highest business impact, rate this news headline: '{t}'. Reply with only the number.")
generate_subject = lambda t: openai_chat(f"Write a 6-8 word email subject for headline: '{t}'.")
generate_email   = lambda t,p: openai_chat(f"Persona: {p}\nHeadline: {t}\nWrite a concise outreach email.", temp=0.7)

# --- Main process ---
if st.button("🔍 Fetch & Analyze Relevant News"):
    with st.spinner("Loading news..."):
        raw_news = fetch_recent_news(keywords_by_sector[sector])
        if not raw_news:
            st.warning("No news from the last week found.")
        else:
            with st.expander("Raw fetched news"):
                for item in raw_news:
                    st.write(item)

            filtered = filter_news_with_gpt(raw_news)
            if not filtered:
                st.warning("GPT found no relevant news.")
            else:
                st.success("GPT filtered relevant news.")
                for i, row in enumerate(filtered.split("\n")):
                    if "|" not in row:
                        continue
                    title, link, pubDate = [p.strip() for p in row.split("|", 2)]
                    st.markdown(f"### {i+1}. {title}")
                    st.markdown(f"🗓️ {pubDate} | 🔗 [Source]({link})")

                    persona = assign_persona(title)
                    impact  = score_impact(title)
                    subject = generate_subject(title)
                    email   = generate_email(title, persona)

                    st.write(f"**📊 Impact Score:** {impact}/5")
                    st.write(f"**👤 Persona:** {persona}")
                    st.text_input("✉️ Subject", subject, key=f"subject_{i}")
                    st.text_area("📧 Email draft", email, height=200, key=f"email_{i}")

                    if st.button("📋 Copy to clipboard", key=f"copy_{i}"):
                        pyperclip.copy(f"Subject: {subject}\n\n{email}")
                        st.success("Email copied to clipboard. Paste into Outlook to send.")
