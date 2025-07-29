import streamlit as st
import feedparser
import openai
import pyperclip
import datetime
from email.utils import parsedate_to_datetime

# --- Access protection & API key from Secrets ---
PASSWORD = st.secrets["PASSWORD"]
openai.api_key = st.secrets["OPENAI_API_KEY"]

password_input = st.text_input("Please enter password:", type="password")
if password_input != PASSWORD:
    st.error("Invalid password!")
    st.stop()

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
        f"https://www.bing.com/news/search?q={query}&format=rss"
    ]
    one_week_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    entries = []
    seen_links = set()

    for url in feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            try:
                pub_dt = parsedate_to_datetime(entry.get("published", ""))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
                else:
                    pub_dt = pub_dt.astimezone(datetime.timezone.utc)
            except Exception:
                continue
            if pub_dt < one_week_ago:
                continue

            link = entry.get("link", "")
            if link in seen_links:
                continue
            seen_links.add(link)

            title = entry.get("title", "")
            pub_str = entry.get("published", "")
            entries.append(f"{title} | {link} | {pub_str}")
            if len(entries) >= 20:
                break
    return entries

# --- GPT: Filter relevant articles ---
def filter_news_with_gpt(news_list):
    headlines = "\n".join(news_list)
    prompt = f"""You are a research assistant for Sales at Oxford Economics.
From this list of headlines (Title | Link | pubDate), return only those that are clearly B2B-relevant to European companies in the selected sector or relevant macro topics (tariffs, trade policy, supply-chain risk).
Prioritize Bloomberg and Reuters content.

Output each item as: Title | Link | pubDate | Region, one per line, sorted newest first:

{headlines}
"""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# --- GPT: Assign persona ---
def assign_persona(title):
    prompt = f"""You are a B2B economics salesperson at Oxford Economics.
Given this headline: "{title}", list the single most relevant persona (job title) to target, such as 'COO' or 'Supply Chain Director'."""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# --- GPT: Score impact (1–5) ---
def score_impact(title):
    prompt = f"""On a scale of 1–5, where 5 = highest business impact, rate this news headline for B2B clients in the selected sector: "{title}". Reply with only the number."""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# --- GPT: Generate email body ---
def generate_email(title, persona):
    prompt = f"""You are a B2B outreach specialist at Oxford Economics.
Use this news headline to write a concise outreach email that:
- Explains the news (no source),
- Describes a plausible business impact,
- Mentions Oxford Economics’ economic insight,
- Invites the recipient to a brief call.

Persona: {persona}
Headline: {title}

Keep it professional, helpful, and to the point."""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

# --- GPT: Generate subject line ---
def generate_subject(title):
    prompt = f"""Based on this news headline, write a 6–8-word email subject line that would encourage a busy executive to open: "{title}". Keep it punchy."""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

# --- Main process ---
if st.button("🔍 Fetch & Analyze Relevant News"):
    with st.spinner("Loading news..."):
        raw_news = fetch_recent_news(keywords_by_sector[sector])
        if not raw_news:
            st.warning("No news from the last week found.")
        else:
            with st.expander("Raw fetched news"):
                for entry in raw_news:
                    st.write(entry)

            filtered = filter_news_with_gpt(raw_news)
            if not filtered:
                st.warning("GPT found no relevant news.")
            else:
                st.success("GPT filtered relevant news.")
                rows = filtered.split("\n")
                for i, row in enumerate(rows):
                    if "|" not in row:
                        continue
                    title, link, pubDate = [p.strip() for p in row.split("|", 2)]
                    st.markdown(f"### {i+1}. {title}")
                    st.markdown(f"🗓️ {pubDate} | 🔗 [Source]({link})")

                    impact = score_impact(title)
                    persona = assign_persona(title)
                    subject = generate_subject(title)
                    email = generate_email(title, persona)

                    st.write(f"**📊 Impact Score:** {impact}/5")
                    st.write(f"**👤 Persona:** {persona}")
                    st.text_input("✉️ Subject", subject, key=f"subject_{i}")
                    st.text_area("📧 Email draft", email, height=200, key=f"email_{i}")

                    if st.button("📋 Copy to clipboard", key=f"copy_{i}"):
                        pyperclip.copy(f"Subject: {subject}\n\n{email}")
                        st.success("Email copied to clipboard. Paste into Outlook to send.")
