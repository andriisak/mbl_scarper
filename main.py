from playwright.sync_api import sync_playwright
import time
import os
import re

SEARCH_BASE_URL = "https://www.mbl.is/frettir/search/?qs={keyword}&offset={offset}&limit=20&sort=1&period=0"
OUTPUT_FILE = "articles.txt"
DONE_FILE = "scraped_urls.txt"
CF_WAIT_SECONDS = 10


def load_done_urls():
    """Load the set of already-scraped URLs."""
    if not os.path.exists(DONE_FILE):
        return set()
    with open(DONE_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def get_article_links(browser, keyword):
    """Extract all article links by paginating through search results."""
    all_links = []
    seen_hrefs = set()
    offset = 0

    while True:
        ctx = browser.new_context()
        page = ctx.new_page()
        url = SEARCH_BASE_URL.format(keyword=keyword, offset=offset)
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(CF_WAIT_SECONDS)

        links = page.eval_on_selector_all(
            "a",
            r"""els => {
                return els
                    .map(e => ({href: e.href, text: e.innerText.trim()}))
                    .filter(l =>
                        /mbl\.is\/(frettir|folk|sport|vidskipti|smartland|menning)\/.*\/\d{4}\//.test(l.href)
                        && l.text.length > 10
                    );
            }""",
        )

        # Check if there's a next page
        has_next = page.query_selector("span.next") is not None

        ctx.close()

        # Deduplicate and add new links
        new_count = 0
        for link in links:
            if link["href"] not in seen_hrefs:
                seen_hrefs.add(link["href"])
                all_links.append(link)
                new_count += 1

        print(f"  Page {offset // 20 + 1}: found {new_count} new links")

        if not has_next or new_count == 0:
            break

        offset += 20

    return all_links


def scrape_article(browser, url, wait_seconds):
    """Open a fresh context, navigate to article, extract date + body."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(wait_seconds)

    # Check for Cloudflare challenge
    title_el = page.query_selector("h1")
    if title_el:
        title_text = title_el.inner_text().strip()
    else:
        title_text = None
    if title_text in (None, "www.mbl.is", "Just a moment..."):
        ctx.close()
        return None, None

    # Extract the publication date from meta tag or URL
    date = None
    meta_date = page.eval_on_selector_all(
        "meta[name='cXenseParse:publishtime']",
        "els => els.map(e => e.getAttribute('content'))",
    )
    if meta_date and meta_date[0]:
        # Parse "2025-05-28T08:36:00+0000" into "28.5.2025"
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", meta_date[0])
        if m:
            date = f"{int(m.group(3))}.{int(m.group(2))}.{m.group(1)}"
    if not date:
        # Fallback: extract from URL like .../2025/05/28/...
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", url)
        if m:
            date = f"{int(m.group(3))}.{int(m.group(2))}.{m.group(1)}"

    # Extract body text
    body = None
    paragraphs = page.eval_on_selector_all(
        ".main-layout p",
        "els => els.map(e => e.innerText.trim()).filter(t => t.length > 0)",
    )
    if paragraphs:
        body = "\n\n".join(paragraphs)

    if not body:
        paragraphs = page.eval_on_selector_all(
            ".frett-container p, article p",
            "els => els.map(e => e.innerText.trim()).filter(t => t.length > 0)",
        )
        if paragraphs:
            body = "\n\n".join(paragraphs)

    ctx.close()
    return date, body


def scrape_articles(keyword, max_articles, wait_seconds):
    done_urls = load_done_urls()
    print(f"Already scraped {len(done_urls)} articles from previous runs.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        print(f"Searching for '{keyword}'...")
        articles = get_article_links(browser, keyword)

        # Filter out already-scraped URLs
        remaining = [a for a in articles if a["href"] not in done_urls]
        to_scrape = remaining if max_articles == 0 else remaining[:max_articles]
        total = len(to_scrape)
        print(f"Found {len(articles)} links, {len(remaining)} new, scraping {total}.\n")

        scraped = 0
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f, \
             open(DONE_FILE, "a", encoding="utf-8") as done_f:
            for i, article in enumerate(to_scrape, 1):
                url = article["href"]
                print(f"Scraping {i}/{total}: {url}")

                try:
                    date, body = scrape_article(browser, url, wait_seconds)
                    if date is None and body is None:
                        print("  -> Blocked by Cloudflare, skipping.")
                        continue
                    if date:
                        f.write(f"{date}\n")
                    f.write(body or "(no body text found)")
                    f.write("\n\n")
                    done_f.write(url + "\n")
                    done_f.flush()
                    scraped += 1
                    print(f"  -> Saved ({date})")
                except Exception as e:
                    print(f"  -> Error: {e}")

        browser.close()
        failed = total - scraped
        print(f"\nDone. {scraped}/{total} successful, {failed} failed. Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    keyword = input("Search keyword: ")
    max_articles = input("Max articles to scrape (0 = all, default: 0): ").strip()
    max_articles = int(max_articles) if max_articles else 0
    wait_seconds = input("Wait between articles in seconds (default: 5): ").strip()
    wait_seconds = int(wait_seconds) if wait_seconds else 5
    scrape_articles(keyword, max_articles, wait_seconds)
