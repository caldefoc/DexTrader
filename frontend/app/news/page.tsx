"use client";

import { useState, useEffect } from "react";
import { BACKEND_URL } from "../../constants/config";

interface NewsArticle {
  title: string;
  link: string;
  published: string;
  source: string;
  summary: string;
  thumbnail: string;
}

interface FeedArticles {
  source: string;
  articles: NewsArticle[];
}

type ViewMode = "grouped" | "chronological";

// Parse various date formats and return sortable timestamp
function parseDate(dateStr: string): number {
  if (!dateStr || dateStr === "Unknown date") return 0;
  try {
    const date = new Date(dateStr);
    return isNaN(date.getTime()) ? 0 : date.getTime();
  } catch {
    return 0;
  }
}

export default function NewsPage() {
  const [feeds, setFeeds] = useState<FeedArticles[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<string>("all");
  const [viewMode, setViewMode] = useState<ViewMode>("chronological");

  useEffect(() => {
    fetchNews();
  }, []);

  const fetchNews = async (forceRefresh = false) => {
    try {
      setLoading(true);
      setError(null);
      const url = `${BACKEND_URL}/news/feeds${forceRefresh ? "?refresh=true" : ""}`;
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error("Failed to fetch news feeds");
      }
      const data = await response.json();
      setFeeds(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch news");
    } finally {
      setLoading(false);
    }
  };

  // Get all unique sources
  const sources = ["all", ...feeds.map((feed) => feed.source)];

  // Filter articles based on selected source
  const filteredFeeds =
    selectedSource === "all"
      ? feeds
      : feeds.filter((feed) => feed.source === selectedSource);

  // Get all articles based on view mode
  const getArticles = (): NewsArticle[] => {
    const articles = filteredFeeds.flatMap((feed) =>
      feed.articles.map((article) => ({ ...article, source: feed.source }))
    );
    
    if (viewMode === "chronological") {
      // Sort by date, most recent first
      return articles.sort((a, b) => parseDate(b.published) - parseDate(a.published));
    }
    
    return articles;
  };

  const allArticles = getArticles();

  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Crypto News</h1>
        <div className="animate-pulse space-y-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="bg-slate-800 rounded-lg p-4 h-24"></div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Crypto News</h1>
        <div className="bg-red-900/30 border border-red-700 rounded-lg p-4">
          <p className="text-red-400">Error loading news: {error}</p>
          <button
            onClick={() => fetchNews(true)}
            className="mt-2 px-4 py-2 bg-red-600 hover:bg-red-700 rounded text-sm"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h1 className="text-2xl font-bold">Crypto News</h1>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm text-gray-400">Source:</label>
          <select
            value={selectedSource}
            onChange={(e) => setSelectedSource(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
          >
            <option value="all">All Sources</option>
            {feeds.map((feed) => (
              <option key={feed.source} value={feed.source}>
                {feed.source} ({feed.articles.length})
              </option>
            ))}
          </select>
          
          <label className="text-sm text-gray-400 ml-2">View:</label>
          <select
            value={viewMode}
            onChange={(e) => setViewMode(e.target.value as ViewMode)}
            className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
          >
            <option value="grouped">Grouped by Source</option>
            <option value="chronological">Chronological</option>
          </select>
          
          <button
            onClick={() => fetchNews(true)}
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded text-sm"
            title="Refresh news"
          >
            ↻
          </button>
        </div>
      </div>

      {viewMode === "grouped" && selectedSource === "all" ? (
        // Show articles grouped by source
        <div className="space-y-8">
          {filteredFeeds.map(
            (feed) =>
              feed.articles.length > 0 && (
                <div key={feed.source} className="space-y-3">
                  <h2 className="text-lg font-semibold text-blue-400 border-b border-slate-700 pb-2">
                    {feed.source}
                  </h2>
                  <div className="grid gap-3">
                    {feed.articles.map((article, index) => (
                      <ArticleCard key={`${feed.source}-${index}`} article={article} />
                    ))}
                  </div>
                </div>
              )
          )}
        </div>
      ) : (
        // Show articles in chronological order or filtered by source
        <div className="space-y-3">
          {allArticles.length > 0 ? (
            allArticles.map((article, index) => (
              <ArticleCard key={index} article={article} />
            ))
          ) : (
            <p className="text-gray-400 text-center py-8">
              No articles available from this source.
            </p>
          )}
        </div>
      )}

      {filteredFeeds.every((feed) => feed.articles.length === 0) && (
        <p className="text-gray-400 text-center py-8">
          No news articles available at the moment.
        </p>
      )}
    </div>
  );
}

function ArticleCard({ article }: { article: NewsArticle }) {
  return (
    <a
      href={article.link}
      target="_blank"
      rel="noopener noreferrer"
      className="block bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 hover:border-slate-600 rounded-lg p-4 transition-colors"
    >
      <div className="flex gap-4">
        {article.thumbnail && (
          <div className="flex-shrink-0">
            <img
              src={article.thumbnail}
              alt=""
              className="w-24 h-16 object-cover rounded"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
          </div>
        )}
        <div className="flex flex-col gap-2 flex-1 min-w-0">
          <h3 className="font-medium text-white hover:text-blue-400 line-clamp-2">
            {article.title}
          </h3>
          {article.summary && (
            <p className="text-sm text-gray-400 line-clamp-2">{article.summary}</p>
          )}
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <span className="text-blue-400">{article.source}</span>
            <span>•</span>
            <span>{article.published}</span>
          </div>
        </div>
      </div>
    </a>
  );
}
