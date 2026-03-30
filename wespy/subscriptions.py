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

import requests
from bs4 import BeautifulSoup


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

                CREATE INDEX IF NOT EXISTS idx_articles_fakeid_create_time
                ON articles(fakeid, create_time DESC);
                """
            )
            self._ensure_column(conn, "articles", "download_status TEXT NOT NULL DEFAULT 'pending'")
            self._ensure_column(conn, "articles", "download_error TEXT")

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
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(fakeid) DO UPDATE SET
                    nickname = excluded.nickname,
                    alias = excluded.alias,
                    avatar = excluded.avatar,
                    signature = excluded.signature,
                    service_type = excluded.service_type,
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

    def list_accounts(self):
        with self._connect() as conn:
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

    def list_accounts(self):
        return self.store.list_accounts()

    def subscribe(self, target):
        client = self._require_client()
        query = target
        if is_wechat_article_url(target):
            query = client.infer_account_name_from_article(target)
            if self.verbose:
                print(f"从文章链接解析到公众号名称: {query}")

        candidates = client.search_accounts(query, begin=0, count=20)
        if not candidates:
            raise RuntimeError(f"未搜索到公众号: {query}")

        matched = self._select_account(candidates, query)
        self.store.upsert_account(matched)
        return matched, query

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
