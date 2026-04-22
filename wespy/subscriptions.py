#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite-backed WeChat subscription storage and sync helpers.
"""

import os
import re
import sqlite3
import time
import urllib.parse
import uuid
import json

import requests
from bs4 import BeautifulSoup

from .extraction_profiles import ProfileResolver


DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".wespy", "wespy.db")


class SubscriptionStore:
    """Persist auth, subscriptions, and discovered articles in SQLite."""

    def __init__(self, db_path=None):
        self.db_path = os.path.abspath(db_path or os.environ.get("WESPY_DB_PATH") or DEFAULT_DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_session (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    token TEXT NOT NULL,
                    cookie TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS accounts (
                    fakeid TEXT PRIMARY KEY,
                    nickname TEXT NOT NULL,
                    alias TEXT,
                    avatar TEXT,
                    signature TEXT,
                    service_type INTEGER,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    latest_article_time INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    last_sync_time INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS articles (
                    link TEXT PRIMARY KEY,
                    fakeid TEXT NOT NULL,
                    aid TEXT,
                    title TEXT NOT NULL,
                    create_time INTEGER NOT NULL DEFAULT 0,
                    itemidx INTEGER,
                    digest TEXT,
                    cover TEXT,
                    is_downloaded INTEGER NOT NULL DEFAULT 0,
                    download_status TEXT NOT NULL DEFAULT 'pending',
                    download_error TEXT,
                    downloaded_at INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(fakeid) REFERENCES accounts(fakeid)
                );

                CREATE TABLE IF NOT EXISTS domains (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS domain_subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain_id INTEGER NOT NULL,
                    fakeid TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    source_value TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(domain_id) REFERENCES domains(id),
                    FOREIGN KEY(fakeid) REFERENCES accounts(fakeid),
                    UNIQUE(domain_id, fakeid)
                );

                CREATE TABLE IF NOT EXISTS article_contents (
                    link TEXT PRIMARY KEY,
                    fakeid TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    publish_time_text TEXT,
                    fetch_status TEXT NOT NULL DEFAULT 'pending',
                    unavailable_reason TEXT,
                    cleaned_html TEXT,
                    cleaned_text TEXT,
                    html_content TEXT,
                    extraction_profile TEXT NOT NULL DEFAULT 'default',
                    normalized_at INTEGER,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(link) REFERENCES articles(link),
                    FOREIGN KEY(fakeid) REFERENCES accounts(fakeid)
                );

                CREATE INDEX IF NOT EXISTS idx_articles_fakeid_create_time
                ON articles(fakeid, create_time DESC);

                CREATE INDEX IF NOT EXISTS idx_domain_subscriptions_domain_enabled
                ON domain_subscriptions(domain_id, enabled);
                """
            )
            self._ensure_column(conn, "accounts", "extraction_profile TEXT")
            self._ensure_column(conn, "accounts", "extraction_profile_version TEXT")
            self._ensure_column(conn, "articles", "download_status TEXT NOT NULL DEFAULT 'pending'")
            self._ensure_column(conn, "articles", "download_error TEXT")
            self._ensure_column(conn, "article_contents", "extraction_profile_version TEXT")
            self._ensure_column(conn, "article_contents", "normalization_notes TEXT")
            self._ensure_column(conn, "article_contents", "ocr_applied INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "article_contents", "ocr_summary TEXT")

    def _ensure_column(self, conn, table, definition):
        column = definition.split()[0]
        existing = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(row["name"] == column for row in existing):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    def set_auth(self, token, cookie):
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_session (id, token, cookie, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    token = excluded.token,
                    cookie = excluded.cookie,
                    updated_at = excluded.updated_at
                """,
                (token.strip(), cookie.strip(), now),
            )

    def get_auth(self):
        with self._connect() as conn:
            row = conn.execute("SELECT token, cookie, updated_at FROM auth_session WHERE id = 1").fetchone()
        return dict(row) if row else None

    def clear_auth(self):
        with self._connect() as conn:
            conn.execute("DELETE FROM auth_session WHERE id = 1")

    def upsert_account(self, account):
        now = int(time.time())
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT latest_article_time, total_count, completed, created_at FROM accounts WHERE fakeid = ?",
                (account["fakeid"],),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO accounts (
                    fakeid, nickname, alias, avatar, signature, service_type,
                    total_count, latest_article_time, completed, last_sync_time,
                    extraction_profile, extraction_profile_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                ON CONFLICT(fakeid) DO UPDATE SET
                    nickname = excluded.nickname,
                    alias = excluded.alias,
                    avatar = excluded.avatar,
                    signature = excluded.signature,
                    service_type = excluded.service_type,
                    extraction_profile = COALESCE(excluded.extraction_profile, accounts.extraction_profile),
                    extraction_profile_version = COALESCE(excluded.extraction_profile_version, accounts.extraction_profile_version),
                    total_count = CASE
                        WHEN excluded.total_count > accounts.total_count THEN excluded.total_count
                        ELSE accounts.total_count
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    account["fakeid"],
                    account["nickname"],
                    account.get("alias"),
                    account.get("avatar"),
                    account.get("signature"),
                    account.get("service_type"),
                    int(account.get("total_count") or 0),
                    int(account.get("latest_article_time") or 0),
                    int(account.get("completed") or 0),
                    account.get("extraction_profile"),
                    account.get("extraction_profile_version"),
                    existing["created_at"] if existing else now,
                    now,
                ),
            )

    def update_account_sync(self, fakeid, total_count=0, latest_article_time=0, completed=False):
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE accounts
                SET
                    total_count = CASE WHEN ? > total_count THEN ? ELSE total_count END,
                    latest_article_time = CASE
                        WHEN ? > latest_article_time THEN ?
                        ELSE latest_article_time
                    END,
                    completed = CASE WHEN ? THEN 1 ELSE completed END,
                    last_sync_time = ?,
                    updated_at = ?
                WHERE fakeid = ?
                """,
                (
                    int(total_count or 0),
                    int(total_count or 0),
                    int(latest_article_time or 0),
                    int(latest_article_time or 0),
                    1 if completed else 0,
                    now,
                    now,
                    fakeid,
                ),
            )

    def upsert_articles(self, fakeid, articles):
        now = int(time.time())
        inserted = 0
        updated = 0

        with self._connect() as conn:
            for article in articles:
                link = normalize_article_url(article.get("link", ""))
                if not link:
                    continue

                exists = conn.execute("SELECT 1 FROM articles WHERE link = ?", (link,)).fetchone()
                conn.execute(
                    """
                    INSERT INTO articles (
                        link, fakeid, aid, title, create_time, itemidx, digest, cover,
                        is_downloaded, download_status, download_error, downloaded_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', NULL, NULL, ?, ?)
                    ON CONFLICT(link) DO UPDATE SET
                        fakeid = excluded.fakeid,
                        aid = excluded.aid,
                        title = excluded.title,
                        create_time = excluded.create_time,
                        itemidx = excluded.itemidx,
                        digest = excluded.digest,
                        cover = excluded.cover,
                        updated_at = excluded.updated_at
                    """,
                    (
                        link,
                        fakeid,
                        str(article.get("aid") or ""),
                        article.get("title") or "未知标题",
                        int(article.get("create_time") or 0),
                        int(article.get("itemidx") or 0),
                        article.get("digest") or "",
                        article.get("cover") or "",
                        now,
                        now,
                    ),
                )
                if exists:
                    updated += 1
                else:
                    inserted += 1

        return inserted, updated

    def create_domain(self, name, description=None, enabled=True):
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO domains (name, description, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = CASE
                        WHEN excluded.description IS NOT NULL AND excluded.description != ''
                        THEN excluded.description ELSE domains.description
                    END,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (name.strip(), (description or "").strip() or None, 1 if enabled else 0, now, now),
            )
            row = conn.execute("SELECT * FROM domains WHERE name = ?", (name.strip(),)).fetchone()
        return dict(row)

    def set_account_profile(self, identifier, profile_name, profile_version=None):
        account = self.get_account(identifier)
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE accounts
                SET extraction_profile = ?, extraction_profile_version = ?, updated_at = ?
                WHERE fakeid = ?
                """,
                (profile_name, profile_version, now, account['fakeid']),
            )
        return self.get_account(account['fakeid'])

    def list_domains(self):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*, COUNT(ds.fakeid) AS active_subscription_count
                FROM domains d
                LEFT JOIN domain_subscriptions ds
                  ON ds.domain_id = d.id AND ds.enabled = 1
                GROUP BY d.id
                ORDER BY d.created_at ASC, d.id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_domain(self, identifier):
        value = str(identifier).strip()
        with self._connect() as conn:
            row = None
            if value.isdigit():
                row = conn.execute("SELECT * FROM domains WHERE id = ?", (int(value),)).fetchone()
            if not row:
                row = conn.execute("SELECT * FROM domains WHERE name = ?", (value,)).fetchone()
        if not row:
            raise RuntimeError(f"未找到领域: {identifier}")
        return dict(row)

    def add_subscription_to_domain(self, domain_identifier, fakeid, source_type='manual', source_value=None):
        domain = self.get_domain(domain_identifier)
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO domain_subscriptions (
                    domain_id, fakeid, enabled, source_type, source_value, created_at, updated_at
                )
                VALUES (?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(domain_id, fakeid) DO UPDATE SET
                    enabled = 1,
                    source_type = excluded.source_type,
                    source_value = excluded.source_value,
                    updated_at = excluded.updated_at
                """,
                (domain['id'], fakeid, source_type, source_value, now, now),
            )
            row = conn.execute(
                "SELECT * FROM domain_subscriptions WHERE domain_id = ? AND fakeid = ?",
                (domain['id'], fakeid),
            ).fetchone()
        return dict(row)

    def remove_subscription_from_domain(self, domain_identifier, fakeid):
        domain = self.get_domain(domain_identifier)
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE domain_subscriptions
                SET enabled = 0, updated_at = ?
                WHERE domain_id = ? AND fakeid = ?
                """,
                (now, domain['id'], fakeid),
            )

    def list_accounts(self, domain=None):
        with self._connect() as conn:
            if domain:
                domain_row = self.get_domain(domain)
                rows = conn.execute(
                    """
                    SELECT
                        a.*,
                        ds.enabled AS domain_subscription_enabled,
                        COUNT(ar.link) AS article_count,
                        SUM(
                            CASE
                                WHEN COALESCE(ar.download_status, 'pending') IN ('pending', 'failed')
                                THEN 1 ELSE 0
                            END
                        ) AS pending_count
                    FROM accounts a
                    JOIN domain_subscriptions ds
                      ON ds.fakeid = a.fakeid
                     AND ds.domain_id = ?
                     AND ds.enabled = 1
                    LEFT JOIN articles ar ON ar.fakeid = a.fakeid
                    GROUP BY a.fakeid, ds.enabled
                    ORDER BY a.updated_at DESC, a.created_at DESC
                    """,
                    (domain_row['id'],),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT
                        a.*,
                        COUNT(ar.link) AS article_count,
                        SUM(
                            CASE
                                WHEN COALESCE(ar.download_status, 'pending') IN ('pending', 'failed')
                                THEN 1 ELSE 0
                            END
                        ) AS pending_count
                    FROM accounts a
                    LEFT JOIN articles ar ON ar.fakeid = a.fakeid
                    GROUP BY a.fakeid
                    ORDER BY a.updated_at DESC, a.created_at DESC
                    """
                ).fetchall()
        return [dict(row) for row in rows]

    def get_account(self, identifier):
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM accounts
                WHERE fakeid = ? OR nickname = ? OR alias = ?
                """,
                (identifier, identifier, identifier),
            ).fetchone()
            if row:
                return dict(row)

            rows = conn.execute(
                """
                SELECT * FROM accounts
                WHERE nickname LIKE ? OR alias LIKE ?
                ORDER BY updated_at DESC
                """,
                (f"%{identifier}%", f"%{identifier}%"),
            ).fetchall()

        if len(rows) == 1:
            return dict(rows[0])
        if len(rows) > 1:
            candidates = ", ".join(f"{row['nickname']}({row['fakeid']})" for row in rows[:5])
            raise RuntimeError(f"匹配到多个公众号，请使用更精确的名称或 fakeid: {candidates}")
        raise RuntimeError(f"未找到公众号: {identifier}")

    def list_articles(self, fakeid, only_undownloaded=True, limit=None):
        sql = "SELECT * FROM articles WHERE fakeid = ?"
        params = [fakeid]
        if only_undownloaded:
            sql += " AND COALESCE(download_status, 'pending') IN ('pending', 'failed')"
        sql += " ORDER BY create_time DESC, rowid DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_domain_articles(self, domain_identifier, start_ts=None, end_ts=None, limit=None):
        domain = self.get_domain(domain_identifier)
        sql = """
            SELECT
                ar.*, a.nickname, a.alias, a.signature,
                ac.fetch_status, ac.cleaned_text, ac.cleaned_html,
                ac.extraction_profile, ac.extraction_profile_version,
                ac.normalization_notes, ac.ocr_applied, ac.ocr_summary
            FROM articles ar
            JOIN domain_subscriptions ds
              ON ds.fakeid = ar.fakeid
             AND ds.domain_id = ?
             AND ds.enabled = 1
            JOIN accounts a ON a.fakeid = ar.fakeid
            LEFT JOIN article_contents ac ON ac.link = ar.link
            WHERE 1 = 1
        """
        params = [domain['id']]
        if start_ts is not None:
            sql += " AND ar.create_time >= ?"
            params.append(int(start_ts))
        if end_ts is not None:
            sql += " AND ar.create_time < ?"
            params.append(int(end_ts))
        sql += " ORDER BY ar.create_time DESC, ar.rowid DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def mark_article_downloaded(self, link):
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE articles
                SET
                    is_downloaded = 1,
                    download_status = 'downloaded',
                    download_error = NULL,
                    downloaded_at = ?,
                    updated_at = ?
                WHERE link = ?
                """,
                (now, now, normalize_article_url(link)),
            )

    def mark_article_unavailable(self, link, reason=None):
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE articles
                SET
                    is_downloaded = 0,
                    download_status = 'unavailable',
                    download_error = ?,
                    updated_at = ?
                WHERE link = ?
                """,
                ((reason or "").strip(), now, normalize_article_url(link)),
            )

    def mark_article_normalized(self, link):
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE articles
                SET
                    is_downloaded = 1,
                    download_status = 'normalized',
                    download_error = NULL,
                    downloaded_at = COALESCE(downloaded_at, ?),
                    updated_at = ?
                WHERE link = ?
                """,
                (now, now, normalize_article_url(link)),
            )

    def upsert_article_content(
        self,
        link,
        fakeid,
        title=None,
        author=None,
        publish_time_text=None,
        fetch_status='normalized',
        unavailable_reason=None,
        cleaned_html=None,
        cleaned_text=None,
        html_content=None,
        extraction_profile='default',
        extraction_profile_version=None,
        normalization_notes=None,
        ocr_applied=0,
        ocr_summary=None,
    ):
        now = int(time.time())
        normalized_link = normalize_article_url(link)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO article_contents (
                    link, fakeid, title, author, publish_time_text, fetch_status,
                    unavailable_reason, cleaned_html, cleaned_text, html_content,
                    extraction_profile, extraction_profile_version, normalization_notes,
                    ocr_applied, ocr_summary, normalized_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(link) DO UPDATE SET
                    fakeid = excluded.fakeid,
                    title = excluded.title,
                    author = excluded.author,
                    publish_time_text = excluded.publish_time_text,
                    fetch_status = excluded.fetch_status,
                    unavailable_reason = excluded.unavailable_reason,
                    cleaned_html = excluded.cleaned_html,
                    cleaned_text = excluded.cleaned_text,
                    html_content = excluded.html_content,
                    extraction_profile = excluded.extraction_profile,
                    extraction_profile_version = excluded.extraction_profile_version,
                    normalization_notes = excluded.normalization_notes,
                    ocr_applied = excluded.ocr_applied,
                    ocr_summary = excluded.ocr_summary,
                    normalized_at = excluded.normalized_at,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_link,
                    fakeid,
                    title,
                    author,
                    publish_time_text,
                    fetch_status,
                    unavailable_reason,
                    cleaned_html,
                    cleaned_text,
                    html_content,
                    extraction_profile,
                    extraction_profile_version,
                    normalization_notes,
                    int(ocr_applied or 0),
                    ocr_summary,
                    now,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM article_contents WHERE link = ?", (normalized_link,)).fetchone()
        return dict(row)

    def get_article_content(self, link):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM article_contents WHERE link = ?", (normalize_article_url(link),)).fetchone()
        return dict(row) if row else None


class WeChatMPClient:
    """Talk to the WeChat public-platform endpoints used for account search and article sync."""

    def __init__(self, token, cookie, verbose=False):
        self.token = str(token).strip()
        self.cookie = (cookie or "").strip()
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WESPY/1.0"
                ),
                "Referer": "https://mp.weixin.qq.com/",
                "Origin": "https://mp.weixin.qq.com",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cookie": self.cookie,
            }
        )

    def search_accounts(self, keyword, begin=0, count=5):
        params = {
            "action": "search_biz",
            "begin": begin,
            "count": count,
            "query": keyword,
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        data = self._get_json("https://mp.weixin.qq.com/cgi-bin/searchbiz", params)
        self._raise_wechat_error(data, "搜索公众号失败")

        result = []
        for item in data.get("list", []):
            result.append(
                {
                    "fakeid": item.get("fakeid") or "",
                    "nickname": item.get("nickname") or "",
                    "alias": item.get("alias") or "",
                    "avatar": item.get("round_head_img") or "",
                    "signature": item.get("signature") or "",
                    "service_type": int(item.get("service_type") or 0),
                    "total_count": 0,
                    "latest_article_time": 0,
                    "completed": 0,
                }
            )
        return result

    def fetch_article_page(self, fakeid, begin=0, count=20):
        params = {
            "sub": "list",
            "search_field": "null",
            "begin": begin,
            "count": count,
            "query": "",
            "fakeid": fakeid,
            "type": "101_1",
            "free_publish_type": 1,
            "sub_action": "list_ex",
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        data = self._get_json("https://mp.weixin.qq.com/cgi-bin/appmsgpublish", params)
        self._raise_wechat_error(data, "获取文章列表失败")

        publish_page_raw = data.get("publish_page") or "{}"
        publish_page = json_loads_safe(publish_page_raw)
        publish_list = [item for item in publish_page.get("publish_list", []) if item.get("publish_info")]
        articles = []

        for item in publish_list:
            publish_info = json_loads_safe(item.get("publish_info") or "{}")
            for article in publish_info.get("appmsgex", []):
                articles.append(
                    {
                        "aid": article.get("aid") or "",
                        "title": article.get("title") or "",
                        "link": normalize_article_url(article.get("link") or ""),
                        "create_time": int(article.get("create_time") or 0),
                        "itemidx": int(article.get("itemidx") or 0),
                        "digest": article.get("digest") or "",
                        "cover": article.get("cover") or "",
                    }
                )

        return {
            "articles": articles,
            "publish_count": len(publish_list),
            "total_count": int(publish_page.get("total_count") or 0),
            "completed": len(publish_list) == 0,
        }

    def infer_account_name_from_article(self, url):
        headers = {
            "Referer": "https://mp.weixin.qq.com/",
            "Origin": "https://mp.weixin.qq.com",
            "User-Agent": self.session.headers["User-Agent"],
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")

        candidates = [
            soup.select_one("#js_name"),
            soup.select_one(".profile_nickname"),
            soup.select_one(".wx_follow_nickname"),
        ]
        for node in candidates:
            if node:
                text = node.get_text(strip=True)
                if text:
                    return text
        raise RuntimeError("无法从文章链接解析公众号名称")

    def fetch_profile_info(self):
        params = {
            "t": "home/index",
            "token": self.token,
            "lang": "zh_CN",
        }
        response = self.session.get("https://mp.weixin.qq.com/cgi-bin/home", params=params, timeout=30)
        response.raise_for_status()
        html = response.text

        nickname = ""
        head_img = ""
        nickname_match = re.search(r'wx\.cgiData\.nick_name\s*=\s*"([^"]*)"', html)
        if nickname_match:
            nickname = nickname_match.group(1)
        head_img_match = re.search(r'wx\.cgiData\.head_img\s*=\s*"([^"]*)"', html)
        if head_img_match:
            head_img = head_img_match.group(1)
        return {"nickname": nickname, "avatar": head_img}

    def _get_json(self, url, params):
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _raise_wechat_error(self, payload, fallback_message):
        base_resp = payload.get("base_resp") or {}
        ret = int(base_resp.get("ret", 0))
        if ret != 0:
            raise RuntimeError(f"{fallback_message}: {ret}:{base_resp.get('err_msg', '未知错误')}")


class SubscriptionService:
    """High-level subscription, sync, and batch-download flow."""

    def __init__(self, store, verbose=False):
        self.store = store
        self.verbose = verbose
        self.profile_resolver = ProfileResolver()

    def set_auth(self, token, cookie):
        self.store.set_auth(token, cookie)

    def get_auth(self):
        return self.store.get_auth()

    def clear_auth(self):
        self.store.clear_auth()

    def login_via_qrcode(self, qr_output_path=None, timeout=180, poll_interval=2):
        login = WeChatMPLogin(verbose=self.verbose)
        result = login.login(qr_output_path=qr_output_path, timeout=timeout, poll_interval=poll_interval)
        self.store.set_auth(result["token"], result["cookie"])
        return result

    def list_domains(self):
        return self.store.list_domains()

    def create_domain(self, name, description=None, enabled=True):
        return self.store.create_domain(name, description=description, enabled=enabled)

    def ensure_default_domain(self):
        return self.store.create_domain("医疗信息", description="医疗信息化领域")

    def resolve_extraction_profile(self, account):
        return self.profile_resolver.resolve_for_account(account)

    def bind_extraction_profile(self, identifier, profile_name):
        profile = self.profile_resolver.get_profile(profile_name)
        return self.store.set_account_profile(identifier, profile['name'], profile.get('version'))

    def list_accounts(self, domain=None):
        return self.store.list_accounts(domain=domain)

    def subscribe(self, target, domain=None):
        client = self._require_client()
        query = target
        if domain == "医疗信息":
            self.ensure_default_domain()
        if is_wechat_article_url(target):
            query = client.infer_account_name_from_article(target)
            if self.verbose:
                print(f"从文章链接解析到公众号名称: {query}")

        candidates = client.search_accounts(query, begin=0, count=20)
        if not candidates:
            raise RuntimeError(f"未搜索到公众号: {query}")

        matched = self._select_account(candidates, query)
        self.store.upsert_account(matched)
        if domain:
            self.store.add_subscription_to_domain(
                domain,
                matched['fakeid'],
                source_type='article_url' if is_wechat_article_url(target) else 'manual',
                source_value=target,
            )
        return matched, query

    def unsubscribe(self, identifier, domain):
        account = self.store.get_account(identifier)
        self.store.remove_subscription_from_domain(domain, account['fakeid'])
        return {
            'account': account,
            'domain': self.store.get_domain(domain),
        }

    def sync_account(self, identifier, max_pages=None):
        client = self._require_client()
        account = self.store.get_account(identifier)
        latest_known = int(account.get("latest_article_time") or 0)
        begin = 0
        page = 0
        inserted_total = 0
        updated_total = 0
        synced_total = 0
        latest_seen = latest_known

        while True:
            if max_pages and page >= int(max_pages):
                break

            page_data = client.fetch_article_page(account["fakeid"], begin=begin, count=20)
            page += 1
            articles = page_data["articles"]

            if not articles:
                self.store.update_account_sync(
                    account["fakeid"],
                    total_count=page_data["total_count"],
                    latest_article_time=latest_seen,
                    completed=True,
                )
                break

            inserted, updated = self.store.upsert_articles(account["fakeid"], articles)
            inserted_total += inserted
            updated_total += updated
            synced_total += len(articles)
            latest_seen = max(latest_seen, max(int(article.get("create_time") or 0) for article in articles))

            if self.verbose:
                print(
                    f"同步第 {page} 页: {len(articles)} 篇文章, 新增 {inserted} 篇, 更新 {updated} 篇"
                )

            oldest_time = min(int(article.get("create_time") or 0) for article in articles)
            self.store.update_account_sync(
                account["fakeid"],
                total_count=page_data["total_count"],
                latest_article_time=latest_seen,
                completed=False,
            )

            if inserted == 0 and oldest_time <= latest_known:
                break

            begin += page_data["publish_count"]
            time.sleep(0.5)

        account = self.store.get_account(account["fakeid"])
        return {
            "account": account,
            "pages": page,
            "new_articles": inserted_total,
            "updated_articles": updated_total,
            "synced_articles": synced_total,
        }

    def download_account(
        self,
        identifier,
        fetcher,
        output_root="articles",
        only_undownloaded=True,
        limit=None,
        save_html=False,
        save_json=False,
        save_markdown=True,
        save_pdf=False,
    ):
        account = self.store.get_account(identifier)
        articles = self.store.list_articles(account["fakeid"], only_undownloaded=only_undownloaded, limit=limit)
        if not articles:
            return {"account": account, "total": 0, "success": 0, "failed": 0, "output_dir": None}

        account_dir = os.path.join(output_root, safe_filename(account["nickname"]) or account["fakeid"])
        os.makedirs(account_dir, exist_ok=True)

        success = 0
        failed = 0
        unavailable = 0
        for index, article in enumerate(articles, 1):
            print(f"[{index}/{len(articles)}] 正在下载: {article['title']}")
            result = fetcher.fetch_article(
                article["link"],
                output_dir=account_dir,
                save_html=save_html,
                save_json=save_json,
                save_markdown=save_markdown,
                save_pdf=save_pdf,
            )
            if result and result.get("fetch_status") == "unavailable":
                self.store.mark_article_unavailable(article["link"], result.get("unavailable_reason"))
                unavailable += 1
                print(f"跳过不可用文章: {result.get('unavailable_reason') or '页面不可访问'}")
            elif result:
                self.store.mark_article_downloaded(article["link"])
                success += 1
            else:
                failed += 1

        return {
            "account": account,
            "total": len(articles),
            "success": success,
            "failed": failed,
            "unavailable": unavailable,
            "output_dir": account_dir,
        }

    def normalize_account(
        self,
        identifier,
        fetcher,
        output_root="articles",
        only_undownloaded=True,
        limit=None,
        save_html=False,
        save_json=False,
        save_markdown=True,
        save_pdf=False,
    ):
        account = self.store.get_account(identifier)
        all_articles = self.store.list_articles(account["fakeid"], only_undownloaded=False, limit=None)
        candidate_statuses = {'pending', 'failed', 'unavailable'}
        articles = [article for article in all_articles if (article.get('download_status') or 'pending') in candidate_statuses]
        if limit:
            articles = articles[: int(limit)]
        if not articles:
            return {"account": account, "total": 0, "success": 0, "failed": 0, "unavailable": 0, "output_dir": None}

        account_dir = os.path.join(output_root, safe_filename(account["nickname"]) or account["fakeid"])
        os.makedirs(account_dir, exist_ok=True)
        profile = self.resolve_extraction_profile(account)

        success = 0
        failed = 0
        unavailable = 0
        for index, article in enumerate(articles, 1):
            print(f"[{index}/{len(articles)}] 正在归一化: {article['title']}")
            result = fetcher.fetch_article(
                article["link"],
                output_dir=account_dir,
                save_html=save_html,
                save_json=save_json,
                save_markdown=save_markdown,
                save_pdf=save_pdf,
            )
            if not result:
                failed += 1
                continue
            if result.get("fetch_status") == "unavailable":
                self.store.mark_article_unavailable(article["link"], result.get("unavailable_reason"))
                self.store.upsert_article_content(
                    article["link"],
                    account["fakeid"],
                    title=result.get("title"),
                    author=result.get("author"),
                    publish_time_text=result.get("publish_time"),
                    fetch_status='unavailable',
                    unavailable_reason=result.get("unavailable_reason"),
                    extraction_profile=profile.get('name', 'default'),
                    extraction_profile_version=profile.get('version'),
                    normalization_notes=result.get('normalization_notes') or json.dumps({
                        'profile': profile.get('name', 'default'),
                        'version': profile.get('version'),
                        'actions': [],
                    }, ensure_ascii=False),
                )
                unavailable += 1
                continue
            cleaned_text, ocr_applied, ocr_summary = self._prepare_ocr_enriched_content(result)
            self.store.upsert_article_content(
                article["link"],
                account["fakeid"],
                title=result.get("title"),
                author=result.get("author"),
                publish_time_text=result.get("publish_time"),
                fetch_status='normalized',
                cleaned_html=result.get("content_html") or '',
                cleaned_text=cleaned_text,
                html_content=result.get("html_content") or '',
                extraction_profile=profile.get('name', 'default'),
                extraction_profile_version=profile.get('version'),
                normalization_notes=result.get('normalization_notes') or json.dumps({
                    'profile': profile.get('name', 'default'),
                    'version': profile.get('version'),
                    'actions': ['ocr_images:1'] if ocr_applied else [],
                }, ensure_ascii=False),
                ocr_applied=1 if ocr_applied else 0,
                ocr_summary=ocr_summary,
            )
            self.store.mark_article_normalized(article["link"])
            success += 1

        return {
            "account": account,
            "total": len(articles),
            "success": success,
            "failed": failed,
            "unavailable": unavailable,
            "output_dir": account_dir,
        }

    def _prepare_ocr_enriched_content(self, result):
        cleaned_text = (result.get('content_text') or '').strip()
        fragments = []
        for fragment in result.get('ocr_fragments') or []:
            text = (fragment.get('text') or fragment.get('preview') or '').strip()
            if len(text) < 8:
                continue
            if text and text not in cleaned_text:
                fragments.append(text)

        if fragments:
            ocr_block = "\n\n".join(fragments)
            merged_text = f"{cleaned_text}\n\n{ocr_block}".strip() if cleaned_text else ocr_block
            summary = "；".join((fragment.get('preview') or fragment.get('text') or '').strip() for fragment in result.get('ocr_fragments') or [] if (fragment.get('preview') or fragment.get('text') or '').strip())
            return merged_text, True, summary[:500]

        if result.get('ocr_applied'):
            summary = (result.get('ocr_summary') or '').strip() or None
            return cleaned_text, True, summary

        return cleaned_text, False, None

    def _require_client(self):
        auth = self.store.get_auth()
        if not auth:
            raise RuntimeError(
                "未配置公众号后台认证信息。请先执行 `wespy-plus auth login`，"
                "或使用 `wespy-plus auth set --token ... --cookie ...` 手动配置。"
            )
        return WeChatMPClient(auth["token"], auth["cookie"], verbose=self.verbose)

    def _select_account(self, candidates, query):
        exact_matches = [
            item for item in candidates if item["nickname"] == query or (item.get("alias") or "") == query
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(candidates) == 1:
            return candidates[0]
        if len(exact_matches) > 1:
            candidates = exact_matches

        summary = "\n".join(
            f"- {item['nickname']} ({item['fakeid']}) alias={item.get('alias') or '-'}"
            for item in candidates[:10]
        )
        raise RuntimeError(f"搜索到多个公众号，请使用更精确的名称重试:\n{summary}")


def normalize_article_url(url):
    value = (url or "").strip()
    if value.endswith("#rd"):
        value = value[:-3]
    return value


def is_wechat_article_url(value):
    return "mp.weixin.qq.com/s/" in (value or "")


def safe_filename(value):
    return re.sub(r'[<>:"/\\|?*]', "_", value or "").strip()


def json_loads_safe(raw):
    try:
        import json

        return json.loads(raw)
    except Exception:
        return {}


class WeChatMPLogin:
    """CLI-oriented QR-code login flow for mp.weixin.qq.com."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WESPY/1.0"
                ),
                "Referer": "https://mp.weixin.qq.com/",
                "Origin": "https://mp.weixin.qq.com",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )

    def login(self, qr_output_path=None, timeout=180, poll_interval=2):
        self._start_login_session()
        qr_path = self._download_qrcode(qr_output_path)
        deadline = time.time() + timeout
        last_message = ""

        while time.time() < deadline:
            status = self._poll_scan_status()
            code = int(status.get("status", -1))

            if code == 0:
                message = "等待扫码"
            elif code in (4, 6):
                if int(status.get("acct_size", 0) or 0) >= 1:
                    message = "已扫码，等待手机确认"
                else:
                    raise RuntimeError("已扫码，但当前账号没有可登录的公众号")
            elif code == 1:
                result = self._finish_login()
                result["qr_path"] = qr_path
                return result
            elif code in (2, 3):
                qr_path = self._download_qrcode(qr_output_path)
                message = "二维码已刷新，请重新扫码"
            elif code == 5:
                raise RuntimeError("该账号尚未绑定邮箱，无法扫码登录公众号平台")
            else:
                message = f"登录状态变更: {code}"

            if message != last_message:
                print(message)
                last_message = message
            time.sleep(poll_interval)

        raise RuntimeError(f"扫码登录超时，请重试。二维码文件: {qr_path}")

    def _start_login_session(self):
        sid = f"{int(time.time() * 1000)}{str(uuid.uuid4().int)[:3]}"
        payload = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "login_type": 3,
            "sessionid": sid,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        response = self.session.post(
            "https://mp.weixin.qq.com/cgi-bin/bizlogin",
            params={"action": "startlogin"},
            data=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        base_resp = data.get("base_resp") or {}
        if int(base_resp.get("ret", 0)) != 0:
            raise RuntimeError(f"初始化登录会话失败: {base_resp.get('err_msg', '未知错误')}")

    def _download_qrcode(self, qr_output_path=None):
        output_path = os.path.abspath(
            qr_output_path
            or os.environ.get("WESPY_QR_PATH")
            or os.path.join(os.path.expanduser("~"), ".wespy", "login-qrcode.png")
        )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        response = self.session.get(
            "https://mp.weixin.qq.com/cgi-bin/scanloginqrcode",
            params={"action": "getqrcode", "random": int(time.time() * 1000)},
            timeout=30,
        )
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"二维码已保存: {output_path}")
        return output_path

    def _poll_scan_status(self):
        response = self.session.get(
            "https://mp.weixin.qq.com/cgi-bin/scanloginqrcode",
            params={"action": "ask", "token": "", "lang": "zh_CN", "f": "json", "ajax": 1},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        base_resp = data.get("base_resp") or {}
        if int(base_resp.get("ret", 0)) != 0:
            raise RuntimeError(f"轮询扫码状态失败: {base_resp.get('err_msg', '未知错误')}")
        return data

    def _finish_login(self):
        payload = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "cookie_forbidden": 0,
            "cookie_cleaned": 0,
            "plugin_used": 0,
            "login_type": 3,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        }
        response = self.session.post(
            "https://mp.weixin.qq.com/cgi-bin/bizlogin",
            params={"action": "login"},
            data=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("err"):
            raise RuntimeError(str(data["err"]))

        redirect_url = data.get("redirect_url") or ""
        token = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_url).query).get("token", [""])[0]
        if not token:
            raise RuntimeError(f"登录成功但未解析到 token: {redirect_url}")

        cookie = "; ".join(f"{cookie.name}={cookie.value}" for cookie in self.session.cookies)
        if not cookie:
            raise RuntimeError("登录成功但未获取到 Cookie")

        client = WeChatMPClient(token, cookie, verbose=self.verbose)
        profile = client.fetch_profile_info()
        return {
            "token": token,
            "cookie": cookie,
            "nickname": profile.get("nickname") or "",
            "avatar": profile.get("avatar") or "",
        }
