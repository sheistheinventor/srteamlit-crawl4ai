# Lead Enrichment Tool

A Streamlit app that enriches moving company leads by crawling their websites.

## What it does
- Upload your lead spreadsheet (xlsx or csv)
- Select the website URL column and business name column
- It crawls each website and extracts:
  - **Owner name**
  - **Multi-location signals** (flags large companies)
  - **Existing review tools** (Podium, Birdeye, Yext, etc.)
- Download the enriched spreadsheet

## How to deploy
1. Fork or upload this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Set main file path to `app.py`
5. Deploy

## Local development
```bash
pip install -r requirements.txt
crawl4ai-setup
streamlit run app.py
```
