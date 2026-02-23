import streamlit as st
import pandas as pd
import asyncio
import json
import re
from io import BytesIO

st.set_page_config(page_title="Lead Enrichment Tool", page_icon="🔍", layout="wide")

st.title("🔍 Lead Enrichment Tool")
st.markdown("Upload your spreadsheet, select the website column, and we'll enrich each business with owner name, location signals, and existing review tools.")

# ── helpers ──────────────────────────────────────────────────────────────────

REVIEW_TOOL_KEYWORDS = [
    "podium", "birdeye", "grade.us", "reviewtrackers", "reputation.com",
    "yext", "trustpilot", "reviewbuzz", "swell", "broadly", "signpost",
    "widewail", "gominga", "rize reviews", "synup"
]

MULTI_LOCATION_KEYWORDS = [
    "locations", "our locations", "find a location", "service areas",
    "branches", "franchise", "nationwide", "offices", "headquarters"
]

def detect_review_tools(text: str) -> str:
    text_lower = text.lower()
    found = [tool for tool in REVIEW_TOOL_KEYWORDS if tool in text_lower]
    return ", ".join(found) if found else "None detected"

def detect_multi_location(text: str) -> str:
    text_lower = text.lower()
    found = [kw for kw in MULTI_LOCATION_KEYWORDS if kw in text_lower]
    return "Yes" if found else "No"

def extract_owner_name(text: str) -> str:
    """Simple heuristic: look for 'founded by', 'owner', 'president', etc."""
    patterns = [
        r'(?:founded by|owner|president|ceo|principal|proprietor)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)',
        r'(?:meet|about)\s+([A-Z][a-z]+ [A-Z][a-z]+)',
        r'([A-Z][a-z]+ [A-Z][a-z]+),?\s+(?:owner|founder|president|ceo)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "Not found"

async def crawl_website(url: str) -> dict:
    """Crawl a single website and extract enrichment data."""
    result = {
        "owner_name": "Not found",
        "multi_location": "Unknown",
        "review_tools": "None detected",
        "has_website": "Yes",
        "crawl_status": "Success"
    }

    if not url or pd.isna(url) or str(url).strip() == "":
        result["has_website"] = "No"
        result["crawl_status"] = "No URL"
        return result

    url = str(url).strip()
    if not url.startswith("http"):
        url = "https://" + url

    try:
        from crawl4ai import AsyncWebCrawler
        from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig

        browser_config = BrowserConfig(headless=True, verbose=False)
        crawl_config = CrawlerRunConfig(
            word_count_threshold=10,
            excluded_tags=["nav", "footer", "header"],
            exclude_external_links=True,
        )

        async with AsyncWebCrawler(config=browser_config) as crawler:
            response = await crawler.arun(url=url, config=crawl_config)

            if response.success:
                text = response.markdown or ""
                result["owner_name"] = extract_owner_name(text)
                result["multi_location"] = detect_multi_location(text)
                result["review_tools"] = detect_review_tools(text)
            else:
                result["crawl_status"] = "Failed to load"

    except ImportError:
        # Fallback if crawl4ai not installed - use basic requests
        try:
            import requests
            from bs4 import BeautifulSoup
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, timeout=10, headers=headers)
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(separator=" ", strip=True)
            result["owner_name"] = extract_owner_name(text)
            result["multi_location"] = detect_multi_location(text)
            result["review_tools"] = detect_review_tools(text)
        except Exception as e:
            result["crawl_status"] = f"Error: {str(e)[:50]}"

    except Exception as e:
        result["crawl_status"] = f"Error: {str(e)[:50]}"

    return result


async def enrich_batch(urls: list, progress_bar, status_text) -> list:
    results = []
    total = len(urls)
    for i, url in enumerate(urls):
        status_text.text(f"Processing {i+1} of {total}: {str(url)[:60]}")
        result = await crawl_website(url)
        results.append(result)
        progress_bar.progress((i + 1) / total)
    return results


# ── UI ────────────────────────────────────────────────────────────────────────

uploaded_file = st.file_uploader("Upload your spreadsheet (.xlsx or .csv)", type=["xlsx", "csv"])

if uploaded_file:
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        st.success(f"✅ Loaded {len(df)} rows and {len(df.columns)} columns")
        st.dataframe(df.head(5), use_container_width=True)

        # Column selector
        col1, col2 = st.columns(2)
        with col1:
            website_col = st.selectbox(
                "Select the column containing website URLs",
                options=df.columns.tolist(),
                index=next((i for i, c in enumerate(df.columns) if "web" in c.lower() or "url" in c.lower() or "site" in c.lower()), 0)
            )
        with col2:
            name_col = st.selectbox(
                "Select the column containing business names",
                options=df.columns.tolist(),
                index=next((i for i, c in enumerate(df.columns) if "name" in c.lower()), 0)
            )

        # Row limit
        max_rows = st.slider("How many rows to process?", min_value=1, max_value=len(df), value=min(50, len(df)))
        df_sample = df.head(max_rows).copy()

        st.info(f"Will enrich {max_rows} businesses. Each crawl takes ~3-5 seconds.")

        if st.button("🚀 Start Enrichment", type="primary"):
            progress_bar = st.progress(0)
            status_text = st.empty()

            urls = df_sample[website_col].tolist()
            results = asyncio.run(enrich_batch(urls, progress_bar, status_text))

            # Add results to dataframe
            df_sample["owner_name"] = [r["owner_name"] for r in results]
            df_sample["multi_location"] = [r["multi_location"] for r in results]
            df_sample["review_tools_detected"] = [r["review_tools"] for r in results]
            df_sample["has_website"] = [r["has_website"] for r in results]
            df_sample["crawl_status"] = [r["crawl_status"] for r in results]

            status_text.text("✅ Done!")
            st.success(f"Enriched {max_rows} businesses!")

            # Show results
            st.subheader("Enriched Results")
            st.dataframe(df_sample[[name_col, website_col, "owner_name", "multi_location", "review_tools_detected", "crawl_status"]], use_container_width=True)

            # Download
            output = BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_sample.to_excel(writer, index=False, sheet_name="Enriched Leads")
            output.seek(0)

            st.download_button(
                label="📥 Download Enriched Spreadsheet",
                data=output,
                file_name="enriched_leads.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    except Exception as e:
        st.error(f"Error reading file: {e}")

else:
    st.info("👆 Upload a spreadsheet to get started")

    with st.expander("What does this tool extract?"):
        st.markdown("""
        For each business website, the tool attempts to find:
        - **Owner Name** — scans About/Team pages for founder or owner mentions
        - **Multi-Location** — detects if the business has multiple locations (flags for removal)
        - **Review Tools** — detects if they already use Podium, Birdeye, Yext, etc.
        - **Crawl Status** — lets you know if a site failed to load
        """)
