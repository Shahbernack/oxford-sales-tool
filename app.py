import streamlit as st
import feedparser
import openai
import pyperclip
import datetime
from email.utils import parsedate_to_datetime

# --- Zugangsschutz & API-Key aus Secrets ---
PASSWORD = st.secrets["PASSWORD"]
openai.api_key = st.secrets["OPENAI_API_KEY"]

pwd = st.text_input("Bitte Passwort eingeben:", type="password")
if pwd != PASSWORD:
    st.error("Ungültiges Passwort!")
    st.stop()

# --- UI ---
st.title("Oxford Economics – Sales Email Tool")

sector = st.selectbox("Wähle einen Sektor", [
    "Professional Services, Government, B2C & Tourism",
    "Real Estate",
    "Asset Management & Financial Services",
    "B2B Manufacturing & Logistics"
])

# --- Keywords für News-Suche pro Sektor ---
keywords_by_sector = {
    "Professional Services, Government, B2C & Tourism": ["services", "government", "tourism", "retail", "public policy"],
    "Real Estate": ["real estate", "property", "construction", "buildings"],
    "Asset Management & Financial Services": ["finance", "banking", "asset management", "investment", "markets"],
    "B2B Manufacturing & Logistics": ["manufacturing", "logistics", "supply chain", "industrial", "infrastructure", "DACH"]
}

# --- News abrufen und nur Artikel der letzten 7 Tage behalten ---
def fetch_recent_news(keywords):
    encoded = [kw.replace(" ", "+") for kw in keywords]
    query = "+".join(encoded)
    feeds = [
        f"https://www.ft.com/news-feed?format=rss"

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

# --- GPT: Filtere relevante Artikel ---
def filter_news_with_gpt(news_list):
    headlines = "\n".join(news_list)
    prompt = f"""Act as a research assistant for Sales at Oxford Economics.
From this list of headlines (Title | Link | pubDate), return only those that are clearly B2B-relevant to companies in Europe in the selected sector or macro-level topics (tariffs, trade policy, supply-chain risk).
Try to use Bloomberg and Reuters first.

Output each item as: Title | Link | pubDate | Region, one per line, sorted newest first:

{headlines}
"""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# --- GPT: Persona zuordnen ---
def assign_persona(title):
    prompt = f"""You are a B2B economics salesperson at Oxford Economics.
Given this headline: "{title}", list the most relevant persona (job title) to target. Just return one short title like 'COO' or 'Supply Chain Director'."""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# --- GPT: Scoring (Impact 1–5) ---
def score_impact(title):
    prompt = f"""On a scale of 1–5, where 5 = highest business impact, rate this news headline for B2B clients in the selected sector: "{title}". Only reply with a single number."""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# --- GPT: E-Mail-Text generieren ---
def generate_email(title, persona):
    prompt = f"""You are a B2B outreach specialist at Oxford Economics.
Use this news headline to write a concise outreach email that:
- Explains the news (no source),
- Outlines a plausible business impact,
- Briefly mentions Oxford Economics’ economic insight,
- Ends with an invitation for a short call.

Persona: {persona}
Headline: {title}

Keep it professional, helpful, short, and not overly salesy."""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

# --- GPT: Subject Line generieren ---
def generate_subject(title):
    prompt = f"""Based on this news headline, write a 6–8-word email subject line that would encourage a busy executive to open: "{title}". Keep it punchy and relevant."""
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

# --- Hauptablauf ---
if st.button("🔍 Relevante News abrufen & analysieren"):
    with st.spinner("Lade News..."):
        raw_news = fetch_recent_news(keywords_by_sector[sector])
        if not raw_news:
            st.warning("Keine News der letzten Woche gefunden.")
        else:
            with st.expander("Roh gefundene News"):
                for entry in raw_news:
                    st.write(entry)
            filtered = filter_news_with_gpt(raw_news)
            if not filtered:
                st.warning("GPT hat keine relevanten News gefunden.")
            else:
                st.success("GPT hat relevante News gefiltert.")
                rows = filtered.split("\n")
                for i, row in enumerate(rows):
                    if "|" not in row:
                        continue
                    title, link, pubDate = [p.strip() for p in row.split("|", 2)]
                    st.markdown(f"### {i+1}. {title}")
                    st.markdown(f"🗓️ {pubDate} | 🔗 [Quelle]({link})")
                    impact = score_impact(title)
                    persona = assign_persona(title)
                    subject = generate_subject(title)
                    email = generate_email(title, persona)
                    st.write(f"**📊 Impact Score:** {impact}/5")
                    st.write(f"**👤 Persona:** {persona}")
                    st.text_input("✉️ Betreff", subject, key=f"subject_{i}")
                    st.text_area("📧 E-Mail-Vorschlag", email, height=200, key=f"email_{i}")
                    if st.button("📋 In Zwischenablage kopieren", key=f"copy_{i}"):
                        pyperclip.copy(f"Subject: {subject}\n\n{email}")
                        st.success("E-Mail in Zwischenablage kopiert. Jetzt in Outlook einfügen.")
