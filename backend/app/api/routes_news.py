"""News RSS feed aggregation API routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
import feedparser
import httpx
import re
from datetime import datetime

# In-memory cache for feeds
_feed_cache: List["FeedArticles"] = []
_cache_timestamp: datetime | None = None
CACHE_DURATION_MINUTES = 30


def strip_html_tags(html_text: str) -> str:
    """Remove HTML tags from text."""
    if not html_text:
        return ""
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', html_text)
    # Remove leading/trailing whitespace
    clean = clean.strip()
    # Decode common HTML entities
    clean = clean.replace('&nbsp;', ' ')
    clean = clean.replace('&amp;', '&')
    clean = clean.replace('&lt;', '<')
    clean = clean.replace('&gt;', '>')
    clean = clean.replace('&quot;', '"')
    clean = clean.replace('&#39;', "'")
    return clean


def extract_summary(entry) -> str:
    """Extract and clean summary from feed entry."""
    # Try multiple possible fields
    summary = ""
    if hasattr(entry, 'summary') and entry.summary:
        summary = entry.summary
    elif hasattr(entry, 'description') and entry.description:
        summary = entry.description
    elif hasattr(entry, 'content') and entry.content:
        # Some feeds put content in a list
        content = entry.content[0] if isinstance(entry.content, list) else entry.content
        if hasattr(content, 'value'):
            summary = content.value
        else:
            summary = str(content)
    
    # Strip HTML tags
    summary = strip_html_tags(summary)
    
    # Limit length
    return summary[:300]

router = APIRouter()

# RSS feed sources from feeds.txt
FEED_SOURCES = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "CryptoSlate": "https://cryptoslate.com/feed",
    "AMBCrypto": "https://ambcrypto.com/feed",
    "BeInCrypto": "https://beincrypto.com/feed",
    "Bitcoinist": "https://bitcoinist.com/feed"
}


class NewsArticle(BaseModel):
    title: str
    link: str
    published: str
    source: str
    summary: str = ""
    thumbnail: str = ""


class FeedArticles(BaseModel):
    source: str
    articles: List[NewsArticle]


async def fetch_all_feeds(force_refresh: bool = False) -> List[FeedArticles]:
    """
    Fetch and return the latest articles from all configured RSS feeds.
    Uses caching unless force_refresh is True.
    Returns maximum 10 most recent entries per feed.
    """
    global _feed_cache, _cache_timestamp
    
    # Check if cache is valid
    if not force_refresh and _cache_timestamp:
        elapsed = (datetime.now() - _cache_timestamp).total_seconds() / 60
        if elapsed < CACHE_DURATION_MINUTES and _feed_cache:
            print(f"Returning cached feeds (cached {elapsed:.1f} minutes ago)")
            return _feed_cache
    
    results = []
    
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for source_name, feed_url in FEED_SOURCES.items():
            try:
                # Fetch the RSS feed
                response = await client.get(feed_url)
                response.raise_for_status()
                
                # Parse the RSS feed
                feed = feedparser.parse(response.text)
                
                articles = []
                # Get up to 10 most recent entries
                for entry in feed.entries[:10]:
                    # Extract thumbnail from various possible locations
                    thumbnail = ""
                    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                        thumbnail = entry.media_thumbnail[0].get('url', '')
                    elif hasattr(entry, 'media_content') and entry.media_content:
                        thumbnail = entry.media_content[0].get('url', '')
                    elif hasattr(entry, 'enclosures') and entry.enclosures:
                        thumbnail = entry.enclosures[0].get('href', '')
                    elif 'image' in entry:
                        thumbnail = entry.image
                    
                    article = NewsArticle(
                        title=entry.get("title", "Untitled"),
                        link=entry.get("link", ""),
                        published=entry.get("published", entry.get("updated", "Unknown date")),
                        source=source_name,
                        summary=extract_summary(entry),
                        thumbnail=thumbnail
                    )
                    articles.append(article)
                
                results.append(FeedArticles(
                    source=source_name,
                    articles=articles
                ))
                
            except Exception as e:
                # Log error but continue with other feeds
                print(f"Error fetching feed {source_name}: {e}")
                results.append(FeedArticles(
                    source=source_name,
                    articles=[]
                ))
    
    # Update cache
    _feed_cache = results
    _cache_timestamp = datetime.now()
    
    return results


@router.get("/feeds", response_model=List[FeedArticles])
async def get_news_feeds(refresh: bool = False) -> List[FeedArticles]:
    """
    Fetch and return the latest articles from all configured RSS feeds.
    Returns maximum 10 most recent entries per feed.
    Set refresh=true to force a fresh fetch.
    """
    return await fetch_all_feeds(force_refresh=refresh)
