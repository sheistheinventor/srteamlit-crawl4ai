import streamlit as st
import pandas as pd
import asyncio
import json
import re
from io import BytesIO

st.set_page_config(page_title="Lead Enrichment Tool", page_icon="🔍", layout="wide")

st.title("🔍 Lead Enrichment Tool")
st.markdown("Upload your spreadsheet, define your niche, and we'll crawl each website to score and qualify your leads.")

# ── Prompt Builder ────────────────────────────────────────────────────────────

def build_prompt(niche: str) -> str:
    return f"""
You are evaluating a business website for a reputation management company.
The target niche is: {niche}

Analyze this website and return ONLY a valid JSON object — no explanation, no markdown, no extra text.

{{
  "fits_niche": true or false,
  "skip_reason": "required string if fits_niche is false, otherwise null",
  "owner_name": "string or null",
  "multi_location": true or false,
  "estimated_company_size": "small / medium / large",
  "score": 0-100,
  "contact_info_found": true or false,
  "site_appears_active": true or false
}}

SCORING GUIDE (score must stay between 0 and 100):
ADD points:
- multi_location = true: +10
- site_appears_active = true: +5

DEDUCT points:
- site_appears_active = false: -20
- contact_info_found = false: -20

If fits_niche is false, skip_reason must be a clear one-sentence explanation.
If fits_niche is false, still attempt to fill remaining fields where possible.
Score cannot go below 0 or above 100.
""".strip()


# ── Crawl Function ────────────────────────────────────────────────────────────

async def crawl_and_extract(url: str, prompt: str) -> dict:
    import requests
    from bs4 import BeautifulSoup
    from openai import OpenAI

    default = {
        "fits_niche": None,
        "skip_reason": "Not crawled",
        "owner_name": None,
        "multi_location": None,
        "estimated_company_size": None,
        "score": 0,
        "contact_info_found": None,
        "site_appears_active": None,
        "crawl_status": "Not attempted"
    }

    if not url or pd.isna(url) or str(url).strip() == "":
        default["skip_reason"] = "No URL provided"
        default["crawl_status"] = "No URL"
        return default

    url = str(url).strip()
    if not url.startswith("http"):
        url = "https://" + url

    # Step 1: Fetch the page with requests (no browser needed)
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "noscript", "nav", "footer"]):
            tag.decompose()

        page_text = soup.get_text(separator=" ", strip=True)
        page_text = page_text[:8000]

    except Exception as e:
        default["crawl_status"] = f"Fetch error: {str(e)[:60]}"
        return default

    # Step 2: Send to OpenAI for analysis
    try:
        client = OpenAI(api_key=st.session_state.get("openai_key", ""))

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Website URL: {url}\n\nWebsite content:\n{page_text}"}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)
        data["crawl_status"] = "Success"
        data["score"] = max(0, min(100, int(data.get("score", 0))))

        fn = data.get("fits_niche")
        if isinstance(fn, str):
            data["fits_niche"] = fn.lower() == "true"

        return data

    except json.JSONDecodeError as e:
        default["crawl_status"] = f"JSON parse error: {str(e)[:40]}"
        return default
    except Exception as e:
        default["crawl_status"] = f"OpenAI error: {str(e)[:60]}"
        return default


async def enrich_batch(urls, prompt, progress_bar, status_text):
    results = []
    total = len(urls)
    for i, url in enumerate(urls):
        status_text.text(f"Crawling {i+1} of {total}: {str(url)[:70]}")
        result = await crawl_and_extract(url, prompt)
        results.append(result)
        progress_bar.progress((i + 1) / total)
    return results


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Configuration")
    openai_key = st.text_input("OpenAI API Key", type="password", help="Required for AI extraction")
    if openai_key:
        st.session_state["openai_key"] = openai_key
        st.success("✅ API key saved")

    st.markdown("---")
    st.markdown("**Score Thresholds**")
    min_score = st.slider("Minimum score to include in qualified list", 0, 100, 30)
    st.caption(f"Leads below {min_score} will be excluded from the qualified download")


# ── Niche Definition ──────────────────────────────────────────────────────────

st.subheader("🎯 Step 1 — Define Your Niche")
st.caption("Be specific. This is passed directly to the AI when it reads each website.")

niche_input = st.text_area(
    "What type of business are you targeting?",
    value="Moving companies, movers, relocation services, and moving & storage businesses. "
          "These are local or regional companies that help people and businesses move their "
          "belongings from one location to another. They typically offer packing, loading, "
          "transport, and storage services.",
    height=110,
)

st.markdown("---")

# ── File Upload ───────────────────────────────────────────────────────────────

st.subheader("📂 Step 2 — Upload Your Spreadsheet")
uploaded_file = st.file_uploader("Upload .xlsx or .csv", type=["xlsx", "csv"])

if uploaded_file:
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        st.success(f"✅ Loaded {len(df)} rows")
        st.dataframe(df.head(5), use_container_width=True)

        col1, col2 = st.columns(2)
        with col1:
            website_col = st.selectbox(
                "Website URL column",
                options=df.columns.tolist(),
                index=next((i for i, c in enumerate(df.columns) if any(k in c.lower() for k in ["web", "url", "site"])), 0)
            )
        with col2:
            name_col = st.selectbox(
                "Business name column",
                options=df.columns.tolist(),
                index=next((i for i, c in enumerate(df.columns) if "name" in c.lower()), 0)
            )

        max_rows = st.slider("How many rows to process?", 1, len(df), min(25, len(df)))
        df_sample = df.head(max_rows).copy()

        st.info(f"Will crawl {max_rows} websites. Estimated time: {max_rows * 5 // 60}m {max_rows * 5 % 60}s")

        if not st.session_state.get("openai_key"):
            st.warning("⚠️ Add your OpenAI API key in the sidebar to enable AI extraction.")

        # ── Run ───────────────────────────────────────────────────────────
        if st.button("🚀 Start Enrichment", type="primary"):
            if not st.session_state.get("openai_key"):
                st.error("OpenAI API key required. Add it in the sidebar.")
            else:
                prompt = build_prompt(niche_input)
                progress_bar = st.progress(0)
                status_text = st.empty()

                urls = df_sample[website_col].tolist()
                results = asyncio.run(enrich_batch(urls, prompt, progress_bar, status_text))

                results_df = pd.DataFrame(results)
                df_enriched = pd.concat([df_sample.reset_index(drop=True), results_df], axis=1)

                status_text.text("✅ Done!")
                st.session_state["df_enriched"] = df_enriched
                st.session_state["name_col"] = name_col
                st.session_state["website_col"] = website_col
                st.session_state["min_score"] = min_score
                st.session_state["overrides"] = {}

        # ── Results ───────────────────────────────────────────────────────
        if "df_enriched" in st.session_state:
            df_enriched = st.session_state["df_enriched"]
            name_col_s = st.session_state["name_col"]
            website_col_s = st.session_state["website_col"]

            st.divider()
            st.subheader("📊 Step 3 — Review Results")

            fits = df_enriched[df_enriched["fits_niche"] == True]
            doesnt_fit = df_enriched[df_enriched["fits_niche"] == False]
            unclear = df_enriched[df_enriched["fits_niche"].isna()]
            high_score = df_enriched[df_enriched["score"] >= 60]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("✅ Fits Niche", len(fits))
            c2.metric("❌ Doesn't Fit", len(doesnt_fit))
            c3.metric("❓ Unclear", len(unclear))
            c4.metric("🔥 Score 60+", len(high_score))

            # ── Niche Rejection Pop-ups ───────────────────────────────────
            if len(doesnt_fit) > 0:
                st.divider()
                st.subheader("❌ Businesses That Don't Fit Your Niche")
                st.caption("The AI flagged these as outside your niche. Review each one and override if needed.")

                if "overrides" not in st.session_state:
                    st.session_state["overrides"] = {}

                for idx, row in doesnt_fit.iterrows():
                    biz_name = row.get(name_col_s, "Unknown Business")
                    biz_url = row.get(website_col_s, "")
                    skip_reason = row.get("skip_reason", "No reason provided")
                    score = row.get("score", 0)
                    size = row.get("estimated_company_size", "Unknown")

                    with st.expander(f"❌  {biz_name}  —  {biz_url}"):
                        col_a, col_b = st.columns([3, 1])

                        with col_a:
                            st.error(f"**Why it was skipped:** {skip_reason}")
                            col_i1, col_i2 = st.columns(2)
                            col_i1.metric("Score", f"{score}/100")
                            col_i2.metric("Size", size or "Unknown")

                            if row.get("crawl_status") != "Success":
                                st.warning(f"Crawl status: {row.get('crawl_status')}")

                        with col_b:
                            st.markdown("**Your decision:**")
                            override = st.radio(
                                "",
                                ["Skip this one", "Include anyway"],
                                key=f"override_{idx}",
                                label_visibility="collapsed"
                            )
                            st.session_state["overrides"][idx] = override

            # ── Qualified Leads Table ─────────────────────────────────────
            st.divider()
            st.subheader("✅ Qualified Leads")

            overrides = st.session_state.get("overrides", {})
            override_indices = [idx for idx, val in overrides.items() if val == "Include anyway"]

            qualified = df_enriched[
                (df_enriched["fits_niche"] == True) |
                (df_enriched.index.isin(override_indices))
            ].copy()
            qualified = qualified[qualified["score"] >= st.session_state.get("min_score", 30)]
            qualified = qualified.sort_values("score", ascending=False)

            display_cols = [
                name_col_s, website_col_s, "score", "owner_name",
                "estimated_company_size", "multi_location",
                "contact_info_found", "site_appears_active", "crawl_status"
            ]
            display_cols = [c for c in display_cols if c in qualified.columns]

            st.dataframe(qualified[display_cols], use_container_width=True)

            # ── Downloads ─────────────────────────────────────────────────
            st.divider()
            st.subheader("📥 Download")
            col_dl1, col_dl2 = st.columns(2)

            with col_dl1:
                out_q = BytesIO()
                with pd.ExcelWriter(out_q, engine="openpyxl") as writer:
                    qualified.to_excel(writer, index=False, sheet_name="Qualified Leads")
                out_q.seek(0)
                st.download_button(
                    "📥 Qualified Leads Only",
                    data=out_q,
                    file_name="qualified_leads.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            with col_dl2:
                out_all = BytesIO()
                with pd.ExcelWriter(out_all, engine="openpyxl") as writer:
                    df_enriched.to_excel(writer, index=False, sheet_name="All Results")
                out_all.seek(0)
                st.download_button(
                    "📥 All Results (including skipped)",
                    data=out_all,
                    file_name="all_enriched_leads.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    except Exception as e:
        st.error(f"Error reading file: {e}")

else:
    st.info("👆 Upload a spreadsheet above to get started")

    with st.expander("📖 What does this tool extract?"):
        st.markdown("""
        For each business website the AI reads the page and extracts:

        | Field | Description |
        |---|---|
        | ✅ Fits niche | Does this site match your target business type? |
        | ❌ Skip reason | If it doesn't fit — exactly why not |
        | 👤 Owner name | Founder or owner name from About/Team page |
        | 📍 Multi-location | Does the business have multiple locations? |
        | 📏 Company size | Small / Medium / Large estimate |
        | 🏆 Score 0-100 | How likely they need your service |
        | 📞 Contact info | Is contact information visible on site? |
        | 🌐 Site active | Does the site appear active/maintained? |
        """)
