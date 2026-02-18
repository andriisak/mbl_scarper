# mbl.is Scraper

Scrapes articles from mbl.is based on a search keyword.

## Setup

```
pip install -r requirements.txt
playwright install chromium
```

## Usage

```
python main.py
```

You'll be prompted for a search keyword and how many articles to scrape. Results are saved to `articles.txt`.

## Notes

- A browser window will open during scraping — this is needed to bypass Cloudflare
- Previously scraped URLs are tracked in `scraped_urls.txt` to avoid duplicates