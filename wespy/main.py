#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取文章内容的脚本
支持从URL获取网页内容并转换为Markdown格式
"""

import os
import sys
import re
import io
import requests
import urllib.parse
from bs4 import BeautifulSoup, Comment
import time
import json
import argparse
from contextlib import redirect_stdout
from wespy.juejin import JuejinFetcher
from wespy.ocr import MinerUOCRClient
from wespy.pdf_export import AgentBrowserPDFExporter
from wespy.subscriptions import SubscriptionService, SubscriptionStore

class WeChatAlbumFetcher:
    """微信公众号专辑文章列表获取器"""

    def __init__(self):
        self.session = requests.Session()
        # 使用微信浏览器的请求头
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.5',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.8,en;q=0.6',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'https://mp.weixin.qq.com/'
        })

    def is_album_url(self, url):
        """检查是否为微信专辑URL"""
        return 'mp.weixin.qq.com/mp/appmsgalbum' in url

    def parse_album_info(self, album_url):
        """解析专辑URL获取基本信息"""
        try:
            from urllib.parse import urlparse, parse_qs
            query = parse_qs(urlparse(album_url).query)

            biz = query.get('__biz', [''])[0]
            action = query.get('action', [''])[0]
            album_id = query.get('album_id', [''])[0]

            if not biz or not action or not album_id:
                return None

            return {
                'biz': biz,
                'action': action,
                'album_id': album_id,
                'original_url': album_url
            }
        except Exception as e:
            print(f"解析专辑URL失败: {e}")
            return None

    def fetch_album_articles(self, album_url, max_articles=None):
        """
        获取专辑中的所有文章列表

        Args:
            album_url (str): 微信专辑URL
            max_articles (int, optional): 最大获取文章数量，None表示获取所有

        Returns:
            list: 文章信息列表
        """
        album_info = self.parse_album_info(album_url)
        if not album_info:
            print("无法解析专辑URL")
            return []

        print(f"正在获取专辑文章列表...")
        print(f"专辑ID: {album_info['album_id']}")

        articles = []
        begin_msgid = 0
        begin_itemidx = 0
        count = 10  # 每页获取数量

        while True:
            # 构建API请求URL
            api_url = f"https://mp.weixin.qq.com/mp/appmsgalbum"
            params = {
                'action': 'getalbum',
                '__biz': album_info['biz'],
                'album_id': album_info['album_id'],
                'count': str(count),
                'begin_msgid': str(begin_msgid),
                'begin_itemidx': str(begin_itemidx),
                'f': 'json'
            }

            try:
                response = self.session.get(api_url, params=params, timeout=30)
                response.raise_for_status()

                # 解析JSON响应
                data = response.json()

                # 检查响应状态
                if data.get('base_resp', {}).get('ret') != 0:
                    print(f"API返回错误: {data.get('base_resp', {})}")
                    break

                # 提取文章列表
                album_resp = data.get('getalbum_resp', {})
                article_list = album_resp.get('article_list', [])

                if not article_list:
                    print("没有更多文章了")
                    break

                # 处理文章信息
                for article_data in article_list:
                    article_info = {
                        'title': article_data.get('title', ''),
                        'url': article_data.get('url', ''),
                        'msgid': article_data.get('msgid', ''),
                        'create_time': article_data.get('create_time', ''),
                        'cover_img': article_data.get('cover_img_1_1', ''),
                        'itemidx': article_data.get('itemidx', ''),
                        'key': article_data.get('key', '')
                    }

                    # 移除URL中的#rd后缀（如果有）
                    if article_info['url'].endswith('#rd'):
                        article_info['url'] = article_info['url'][:-3]

                    articles.append(article_info)

                    # 检查是否达到最大文章数量限制
                    if max_articles and len(articles) >= max_articles:
                        print(f"已达到最大文章数量限制: {max_articles}")
                        return articles

                print(f"已获取 {len(articles)} 篇文章...")

                # 检查是否还有更多文章
                continue_flag = album_resp.get('continue_flag', '0')
                if continue_flag != '1':
                    print("已获取所有文章")
                    break

                # 更新下一页的起始位置
                if article_list:
                    last_article = article_list[-1]
                    begin_msgid = last_article.get('msgid', 0)
                    begin_itemidx = last_article.get('itemidx', 0)

                # 添加延迟避免请求过快
                time.sleep(0.5)

            except Exception as e:
                print(f"获取文章列表失败: {e}")
                break

        print(f"总共获取到 {len(articles)} 篇文章")
        return articles

class ArticleFetcher:
    PRESERVED_CONTENT_TAGS = {'img', 'picture', 'pre', 'code', 'table', 'blockquote', 'ul', 'ol', 'video', 'iframe'}
    NON_CONTENT_KEYWORDS = [
        'share', 'related', 'recommended', 'subscribe', 'follow us', 'follow me',
        '二维码', '扫码', '进群', '分享', '点赞', '在看', '关注我们', '相关推荐',
        '相关阅读', '推荐阅读', '版权声明', '免责声明', '广告', '赞赏'
    ]
    WECHAT_LEAD_PATTERNS = [
        r'点击上方.*关注',
        r'关注我们',
        r'长按.*识别',
    ]
    WECHAT_TRAILING_PATTERNS = [
        r'点击下方.*阅读原文',
        r'^来源[:：]',
        r'^点分享$',
        r'^点收藏$',
        r'^点点赞$',
        r'^点在看$',
        r'扫码.*进群',
        r'AI进群',
        r'仅限受邀加入',
    ]
    WECHAT_UNAVAILABLE_PATTERNS = [
        r'该内容已被发布者删除',
        r'此内容因违规无法查看',
        r'此内容因投诉无法查看',
        r'内容已被删除',
        r'轻触阅读原文',
        r'微信扫一扫可打开此内容',
        r'使用完整服务',
    ]
    MINERU_IMAGE_MIN_WIDTH = 200

    def __init__(self, enable_image_ocr=False, mineru_url=None, mineru_backend="hybrid-auto-engine", mineru_lang_list=None, verbose=False):
        self.session = requests.Session()
        # 设置请求头，模拟浏览器
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        # 初始化掘金获取器
        self.juejin_fetcher = JuejinFetcher(verbose=verbose)
        # 初始化微信专辑获取器
        self.album_fetcher = WeChatAlbumFetcher()
        self.enable_image_ocr = enable_image_ocr
        self.mineru_url = mineru_url or os.environ.get('WESPY_MINERU_URL') or 'http://172.16.3.132:8523'
        self.mineru_backend = mineru_backend
        self.mineru_lang_list = mineru_lang_list or ['ch']
        self.verbose = verbose
        self.image_ocr_client = (
            MinerUOCRClient(
                server_url=self.mineru_url,
                backend=self.mineru_backend,
                lang_list=self.mineru_lang_list,
            )
            if self.enable_image_ocr else None
        )
        self._image_ocr_cache = {}
        self.pdf_exporter = AgentBrowserPDFExporter(verbose=verbose)

    def fetch_album_articles(self, album_url, output_dir="articles", max_articles=None, save_html=False, save_json=False, save_markdown=True, save_pdf=False):
        """
        批量获取微信专辑中的所有文章

        Args:
            album_url (str): 微信专辑URL
            output_dir (str): 输出目录
            max_articles (int, optional): 最大获取文章数量，None表示获取所有
            save_html (bool): 是否保存HTML文件
            save_json (bool): 是否保存JSON文件
            save_markdown (bool): 是否保存Markdown文件
            save_pdf (bool): 是否保存PDF文件

        Returns:
            list: 成功获取的文章信息列表
        """
        # 获取专辑文章列表
        articles = self.album_fetcher.fetch_album_articles(album_url, max_articles)

        if not articles:
            print("没有获取到任何文章")
            return []

        print(f"\n开始批量下载 {len(articles)} 篇文章...")

        successful_articles = []
        failed_articles = []

        # 创建专辑专用目录
        album_name = f"album_{int(time.time())}"
        album_output_dir = os.path.join(output_dir, album_name)

        for i, article in enumerate(articles, 1):
            print(f"\n[{i}/{len(articles)}] 正在下载: {article['title']}")

            try:
                # 下载单篇文章
                article_result = self.fetch_article(
                    article['url'],
                    album_output_dir,
                    save_html,
                    save_json,
                    save_markdown,
                    save_pdf
                )

                if article_result:
                    # 合并专辑信息
                    article_result.update({
                        'album_title': article.get('title', ''),
                        'album_url': album_url,
                        'msgid': article.get('msgid', ''),
                        'create_time': article.get('create_time', ''),
                        'cover_img': article.get('cover_img', '')
                    })
                    successful_articles.append(article_result)
                    print(f"✅ 下载成功")
                else:
                    print(f"❌ 下载失败")
                    failed_articles.append(article)

                # 添加延迟避免请求过快
                time.sleep(1)

            except Exception as e:
                print(f"❌ 下载失败: {e}")
                failed_articles.append(article)

        # 保存专辑汇总信息
        self._save_album_summary(successful_articles, failed_articles, album_url, output_dir, album_name)

        print(f"\n批量下载完成!")
        print(f"成功: {len(successful_articles)} 篇")
        print(f"失败: {len(failed_articles)} 篇")
        print(f"文章保存在: {album_output_dir}")

        return successful_articles

    def _save_album_summary(self, successful_articles, failed_articles, album_url, output_dir, album_name):
        """保存专辑下载汇总信息"""
        summary = {
            'album_url': album_url,
            'download_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'statistics': {
                'total_count': len(successful_articles) + len(failed_articles),
                'successful_count': len(successful_articles),
                'failed_count': len(failed_articles)
            },
            'successful_articles': [
                {
                    'title': article.get('title', ''),
                    'author': article.get('author', ''),
                    'url': article.get('url', ''),
                    'msgid': article.get('msgid', ''),
                    'create_time': article.get('create_time', '')
                }
                for article in successful_articles
            ],
            'failed_articles': [
                {
                    'title': article.get('title', ''),
                    'url': article.get('url', ''),
                    'msgid': article.get('msgid', ''),
                    'error': '下载失败'
                }
                for article in failed_articles
            ]
        }

        summary_file = os.path.join(output_dir, f"{album_name}_summary.json")
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"专辑汇总信息已保存: {summary_file}")

    def fetch_article(self, url, output_dir="articles", save_html=False, save_json=False, save_markdown=True, save_pdf=False):
        """
        获取文章内容
        
        Args:
            url (str): 文章URL
            output_dir (str): 输出目录
            save_html (bool): 是否保存HTML文件
            save_json (bool): 是否保存JSON文件
            save_markdown (bool): 是否保存Markdown文件
            save_pdf (bool): 是否保存PDF文件
        
        Returns:
            dict: 包含文章信息的字典
        """
        try:
            # 特殊处理微信专辑URL
            if self.album_fetcher.is_album_url(url):
                print("检测到微信专辑URL，将批量下载专辑中的所有文章")
                return self.fetch_album_articles(url, output_dir, max_articles=10, save_html=save_html, save_json=save_json, save_markdown=save_markdown, save_pdf=save_pdf)
            # 特殊处理微信公众号链接
            elif 'mp.weixin.qq.com' in url:
                return self._fetch_wechat_article(url, output_dir, save_html, save_json, save_markdown, save_pdf)
            # 特殊处理掘金链接
            elif 'juejin.cn' in url:
                return self.juejin_fetcher.fetch_article(url, output_dir, save_html, save_json, save_markdown, save_pdf)
            else:
                return self._fetch_general_article(url, output_dir, save_html, save_json, save_markdown, save_pdf)
                
        except Exception as e:
            print(f"获取文章失败: {e}")
            return None
    
    def _fetch_wechat_article(self, url, output_dir, save_html=False, save_json=False, save_markdown=True, save_pdf=False):
        """获取微信公众号文章"""
        print(f"正在获取微信文章: {url}")
        
        # 设置微信特定的请求头
        headers = self.session.headers.copy()
        headers['Referer'] = 'https://mp.weixin.qq.com/'
        
        response = self.session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 提取文章信息
        article_info = self._extract_wechat_info(soup)
        article_info['url'] = url
        article_info['html_content'] = response.text

        unavailable_reason = self._detect_wechat_unavailable_reason(soup, article_info)
        if unavailable_reason:
            print(f"跳过不可用微信文章: {unavailable_reason}")
            return {
                'url': url,
                'title': article_info.get('title') or "未知标题",
                'author': article_info.get('author') or "未知作者",
                'publish_time': article_info.get('publish_time') or "",
                'fetch_status': 'unavailable',
                'unavailable_reason': unavailable_reason,
            }
        
        # 保存文章
        self._save_article(article_info, output_dir, save_html, save_json, save_markdown, save_pdf)
        
        return article_info
    
    def _fetch_general_article(self, url, output_dir, save_html=False, save_json=False, save_markdown=True, save_pdf=False):
        """获取普通网页文章"""
        print(f"正在获取文章: {url}")
        
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        
        # 尝试检测编码
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding or 'utf-8'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 提取文章信息
        article_info = self._extract_general_info(soup)
        article_info['url'] = url
        article_info['html_content'] = response.text
        
        # 保存文章
        self._save_article(article_info, output_dir, save_html, save_json, save_markdown, save_pdf)
        
        return article_info
    
    def _extract_wechat_info(self, soup):
        """提取微信文章信息"""
        info = {}
        
        # 标题
        title_elem = soup.find('h1', {'class': 'rich_media_title'}) or soup.find('h1')
        info['title'] = title_elem.get_text().strip() if title_elem else "未知标题"
        
        # 作者
        author_elem = (soup.find('a', {'id': 'js_name'}) or 
                      soup.find('a', {'class': 'profile_nickname'}) or 
                      soup.find('span', {'class': 'profile_nickname'}))
        info['author'] = author_elem.get_text().strip().replace('\n', '').replace('\r', '').replace('\t', '') if author_elem else "未知作者"
        
        # 发布时间
        time_elem = soup.find('em', {'id': 'publish_time'}) or soup.find('span', {'class': 'publish_time'})
        info['publish_time'] = time_elem.get_text().strip() if time_elem else ""
        # 遇到发布时间是页面渲染时 js set 进去的，所在直接从 html 里取
        if not info['publish_time']:
            m = re.search(
                r"create_time:\s*JsDecode\('([^']+)'\)",
                str(soup)
            )
            if m:
                info['publish_time'] = m.group(1)
        
        # 内容区域
        content_elem = soup.find('div', {'id': 'js_content'})
        if content_elem:
            cleaned_content = self._clean_content_element(content_elem, source='wechat')
            info['content_html'] = str(cleaned_content)
            info['content_text'] = cleaned_content.get_text('\n', strip=True)
        else:
            info['content_html'] = ""
            info['content_text'] = ""
        
        return info

    def _detect_wechat_unavailable_reason(self, soup, article_info):
        """识别微信文章失效页，避免把空壳页保存成正文。"""
        body_text = self._normalize_text(soup.get_text('\n', strip=True))
        title = (article_info.get('title') or '').strip()
        author = (article_info.get('author') or '').strip()
        content_text = self._normalize_text(article_info.get('content_text') or '')
        has_content_container = bool(soup.find('div', {'id': 'js_content'}))

        for pattern in self.WECHAT_UNAVAILABLE_PATTERNS:
            if re.search(pattern, body_text, re.IGNORECASE):
                return re.sub(r'\s+', ' ', pattern).strip('^$')

        looks_like_empty_shell = (
            title in ("", "未知标题")
            and author in ("", "未知作者")
            and not content_text
            and not has_content_container
        )
        if looks_like_empty_shell:
            return "页面未返回可提取的微信正文，疑似已删除或不可访问"

        return None
    
    def _extract_general_info(self, soup):
        """提取普通网页信息"""
        info = {}
        
        # 标题 - 尝试多种方式获取
        title_elem = (soup.find('title') or 
                     soup.find('h1') or 
                     soup.find('h2') or
                     soup.find('meta', {'property': 'og:title'}))
        
        if title_elem:
            if title_elem.name == 'meta':
                info['title'] = title_elem.get('content', '').strip()
            else:
                info['title'] = title_elem.get_text().strip()
        else:
            info['title'] = "未知标题"
        
        # 作者
        author_elem = (soup.find('meta', {'name': 'author'}) or
                      soup.find('span', {'class': re.compile(r'author', re.I)}) or
                      soup.find('div', {'class': re.compile(r'author', re.I)}) or
                      soup.find('a', {'id': 'js_name'}))
        
        if author_elem:
            if author_elem.name == 'meta':
                info['author'] = author_elem.get('content', '').strip()
            else:
                info['author'] = author_elem.get_text().strip()
        else:
            info['author'] = "未知作者"
        
        # 发布时间
        time_elem = (soup.find('time') or
                    soup.find('span', {'class': re.compile(r'time|date', re.I)}) or
                    soup.find('meta', {'property': 'article:published_time'}))
        
        if time_elem:
            if time_elem.name == 'meta':
                info['publish_time'] = time_elem.get('content', '').strip()
            else:
                info['publish_time'] = time_elem.get_text().strip()
        else:
            info['publish_time'] = ""
        
        # 内容区域 - 尝试多种选择器
        content_selectors = [
            'article',
            '.article-content',
            '.content',
            '.post-content',
            '.entry-content',
            '#content',
            '.main-content',
            'main'
        ]
        
        content_elem = None
        for selector in content_selectors:
            content_elem = soup.select_one(selector)
            if content_elem:
                break
        
        if not content_elem:
            # 如果没找到特定内容区域，使用body
            content_elem = soup.find('body')
        
        if content_elem:
            cleaned_content = self._clean_content_element(content_elem, source='general')
            info['content_html'] = str(cleaned_content)
            info['content_text'] = cleaned_content.get_text('\n', strip=True)
        else:
            info['content_html'] = ""
            info['content_text'] = ""

        return info

    def _clean_content_element(self, content_elem, source='general'):
        """清洗提取出的正文内容，尽量保留正文、删除噪音块。"""
        cleaned = BeautifulSoup(str(content_elem), 'html.parser')
        root = cleaned.find()
        if not root:
            return cleaned

        self._remove_comments_and_hidden(root)

        if source == 'wechat':
            self._trim_wechat_lead(root)
            self._trim_wechat_trailing_content(root)

        self._prune_low_value_blocks(root, source)
        self._remove_empty_elements(root)
        return root

    def _remove_comments_and_hidden(self, root):
        """移除注释、脚本、样式和明显隐藏的节点。"""
        for comment in root.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        for tag in root.find_all(['script', 'style', 'noscript']):
            tag.decompose()

        for tag in list(root.find_all(True)):
            if getattr(tag, 'name', None) is None or getattr(tag, 'attrs', None) is None:
                continue
            style = (tag.get('style') or '').lower()
            if tag.has_attr('hidden') or tag.get('aria-hidden') == 'true':
                tag.decompose()
                continue
            if re.search(r'display\s*:\s*none', style) or re.search(r'visibility\s*:\s*hidden', style):
                tag.decompose()

    def _trim_wechat_lead(self, root):
        """移除公众号正文开头常见的引导关注块。"""
        blocks = self._get_text_blocks(root)
        first_substantive = None

        for block in blocks:
            text = self._normalize_text(block.get_text(' ', strip=True))
            if self._is_substantive_text(text):
                first_substantive = block
                break

        if not first_substantive:
            return

        for block in blocks:
            if block == first_substantive:
                break
            text = self._normalize_text(block.get_text(' ', strip=True))
            if self._matches_patterns(text, self.WECHAT_LEAD_PATTERNS):
                self._remove_before_node(first_substantive, root)
                return

    def _trim_wechat_trailing_content(self, root):
        """命中公众号尾部标记后，截断后续所有内容。"""
        full_text = self._normalize_text(root.get_text('\n', strip=True))
        if not full_text:
            return

        for block in self._get_text_blocks(root):
            text = self._normalize_text(block.get_text(' ', strip=True))
            if not text:
                continue

            marker = text[:40]
            position = full_text.find(marker) if marker else -1
            ratio = (position / len(full_text)) if position >= 0 and full_text else 0

            if ratio < 0.45:
                continue

            if self._matches_patterns(text, self.WECHAT_TRAILING_PATTERNS):
                self._remove_after_node(block, root, remove_self=True)
                return

    def _prune_low_value_blocks(self, root, source='general'):
        """删除低价值的结构块，借鉴通用正文清洗的打分思路。"""
        candidates = list(root.find_all(['section', 'div', 'aside']))

        for tag in candidates:
            if getattr(tag, 'name', None) is None or getattr(tag, 'attrs', None) is None:
                continue
            if tag == root:
                continue

            text = self._normalize_text(tag.get_text(' ', strip=True))
            text_weight = self._text_weight(text)

            if text_weight == 0 and not tag.find(list(self.PRESERVED_CONTENT_TAGS)):
                tag.decompose()
                continue

            if self._looks_like_content_container(tag, text_weight):
                continue

            score = 0
            keyword_hits = sum(1 for keyword in self.NON_CONTENT_KEYWORDS if keyword in text.lower())
            link_density = self._link_density(tag, text)
            image_count = len(tag.find_all('img'))
            paragraph_count = len(tag.find_all('p'))

            if text_weight < 8:
                score -= 1
            if keyword_hits:
                score -= keyword_hits
            if link_density > 0.45 and len(tag.find_all('a')) > 1:
                score -= 2
            if image_count >= 2 and text_weight < 12:
                score -= 2
            if paragraph_count == 0 and image_count and text_weight < 16:
                score -= 1
            if source == 'wechat' and any(keyword in text for keyword in ['扫码', '进群', '点分享', '点收藏', '点点赞', '点在看']):
                score -= 3

            if score <= -2:
                tag.decompose()

    def _remove_empty_elements(self, root):
        """清理空包装节点，保留图片、代码、表格等正文元素。"""
        for tag in list(root.find_all(True)):
            if getattr(tag, 'name', None) is None or getattr(tag, 'attrs', None) is None:
                continue
            if tag == root:
                continue
            if tag.name in self.PRESERVED_CONTENT_TAGS or tag.name == 'br':
                continue
            if tag.find(list(self.PRESERVED_CONTENT_TAGS)):
                continue
            if not tag.get_text(strip=True):
                tag.decompose()

    def _get_text_blocks(self, root):
        """获取正文中的文本块，用于定位开头和结尾噪音。"""
        blocks = []
        for tag in root.find_all(['p', 'li', 'blockquote', 'h1', 'h2', 'h3', 'h4']):
            text = self._normalize_text(tag.get_text(' ', strip=True))
            if text:
                blocks.append(tag)
        return blocks

    def _is_substantive_text(self, text):
        """判断是否是较像正文的文本块。"""
        if self._text_weight(text) >= 24:
            return True
        return self._text_weight(text) >= 16 and bool(re.search(r'[。！？；：.!?]', text))

    def _looks_like_content_container(self, tag, text_weight):
        """保留明显像正文的结构块。"""
        if text_weight >= 120:
            return True
        if len(tag.find_all('p')) >= 2 and text_weight >= 24:
            return True
        if tag.find(['pre', 'code', 'table', 'blockquote']) and text_weight >= 12:
            return True
        if tag.find(['img', 'picture']) and text_weight >= 24:
            return True
        return False

    def _link_density(self, tag, text):
        """计算链接文本密度，辅助识别导航和营销块。"""
        total_length = len(re.sub(r'\s+', '', text)) or 1
        link_text = ''.join(link.get_text(' ', strip=True) for link in tag.find_all('a'))
        link_length = len(re.sub(r'\s+', '', link_text))
        return link_length / total_length

    def _text_weight(self, text):
        """兼容中英文的轻量文本权重估算。"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        latin_words = len(re.findall(r'\b[a-zA-Z0-9_]+\b', text))
        return latin_words + chinese_chars // 2

    def _normalize_text(self, text):
        """压缩空白，便于匹配内容模式。"""
        return re.sub(r'\s+', ' ', text or '').strip()

    def _matches_patterns(self, text, patterns):
        """检查文本是否命中任一清洗规则。"""
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    def _remove_after_node(self, node, root, remove_self=False):
        """删除当前节点之后的所有内容，跨层级向上截断。"""
        current = node
        first_step = True

        while current and current != root:
            parent = current.parent if getattr(current, 'parent', None) else None
            if first_step and remove_self:
                next_sibling = current.next_sibling
                current.decompose()
            else:
                next_sibling = current.next_sibling

            while next_sibling is not None:
                sibling = next_sibling
                next_sibling = sibling.next_sibling
                if hasattr(sibling, 'decompose'):
                    sibling.decompose()
                else:
                    sibling.extract()

            first_step = False
            current = parent

    def _remove_before_node(self, node, root):
        """删除当前节点之前的所有内容，跨层级向上截断。"""
        current = node

        while current and current != root:
            prev_sibling = current.previous_sibling
            while prev_sibling is not None:
                sibling = prev_sibling
                prev_sibling = sibling.previous_sibling
                if hasattr(sibling, 'decompose'):
                    sibling.decompose()
                else:
                    sibling.extract()

            current = current.parent if getattr(current, 'parent', None) else None

    def _save_article(self, article_info, output_dir, save_html=False, save_json=False, save_markdown=True, save_pdf=False):
        """保存文章到文件"""
        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 生成安全的文件名
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', article_info['title'])[:50]
        timestamp = int(time.time())
        
        saved_files = []
        
        # 保存HTML文件
        if save_html:
            html_filename = f"{safe_title}_{timestamp}.html"
            html_path = os.path.join(output_dir, html_filename)
            
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(article_info['html_content'])
            
            print(f"HTML文件已保存: {html_path}")
            saved_files.append(('HTML', html_path))

        if save_pdf:
            pdf_filename = f"{safe_title}_{timestamp}.pdf"
            pdf_path = os.path.join(output_dir, pdf_filename)
            try:
                self.pdf_exporter.export_url(article_info['url'], pdf_path)
                print(f"PDF文件已保存: {pdf_path}")
                saved_files.append(('PDF', pdf_path))
            except Exception as e:
                print(f"导出PDF失败: {e}")
        
        # 保存文章信息为JSON
        if save_json:
            info_filename = f"{safe_title}_{timestamp}_info.json"
            info_path = os.path.join(output_dir, info_filename)
            
            info_to_save = {
                'title': article_info['title'],
                'author': article_info['author'],
                'publish_time': article_info['publish_time'],
                'url': article_info['url'],
                'html_file': f"{safe_title}_{timestamp}.html" if save_html else None,
                'pdf_file': f"{safe_title}_{timestamp}.pdf" if save_pdf else None,
                'fetch_time': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump(info_to_save, f, ensure_ascii=False, indent=2)
            
            print(f"文章信息已保存: {info_path}")
            saved_files.append(('JSON', info_path))
        
        # 转换为Markdown (默认保存)
        if save_markdown:
            try:
                markdown_content = self._convert_to_markdown(article_info['content_html'])
                md_filename = f"{safe_title}_{timestamp}.md"
                md_path = os.path.join(output_dir, md_filename)
                
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(f"# {article_info['title']}\n\n")
                    f.write(f"**作者**: {article_info['author']}\n")
                    f.write(f"**发布时间**: {article_info['publish_time']}\n")
                    f.write(f"**原文链接**: {article_info['url']}\n\n")
                    f.write("---\n\n")
                    f.write(markdown_content)
                
                print(f"Markdown文件已保存: {md_path}")
                saved_files.append(('Markdown', md_path))
                
            except Exception as e:
                print(f"转换Markdown失败: {e}")
        
        return saved_files
    
    def _convert_to_markdown(self, html_content):
        """将HTML内容转换为Markdown"""
        if not html_content:
            return ""
        
        soup = BeautifulSoup(html_content, 'html.parser')
        return self._html_to_markdown_recursive(soup)
    
    def _html_to_markdown_recursive(self, element):
        """递归转换HTML元素为Markdown"""
        markdown = ""
        
        for child in element.children:
            if child.name is None:  # 文本节点
                text = str(child).strip()
                if text:
                    markdown += text
            elif child.name == 'br':
                markdown += '\n'
            elif child.name in ['p', 'div', 'section']:
                content = self._html_to_markdown_recursive(child).strip()
                if content:
                    markdown += '\n\n' + content + '\n'
            elif child.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(child.name[1])
                content = self._html_to_markdown_recursive(child).strip()
                if content:
                    markdown += '\n' + '#' * level + ' ' + content + '\n'
            elif child.name in ['strong', 'b']:
                content = self._html_to_markdown_recursive(child).strip()
                if content:
                    markdown += '**' + content + '**'
            elif child.name in ['em', 'i']:
                content = self._html_to_markdown_recursive(child).strip()
                if content:
                    markdown += '*' + content + '*'
            elif child.name == 'img':
                src = child.get('data-src') or child.get('src', '')
                alt = child.get('alt', '')
                if src:
                    markdown += self._render_image_markdown(child, src, alt)
            elif child.name == 'a':
                href = child.get('href', '')
                text = self._html_to_markdown_recursive(child).strip()
                if href and text:
                    markdown += f'[{text}]({href})'
                elif text:
                    markdown += text
            elif child.name in ['ul', 'ol']:
                list_content = self._convert_list_to_markdown(child)
                if list_content:
                    markdown += '\n' + list_content + '\n'
            elif child.name == 'code':
                # 处理行内代码
                code_content = child.get_text().strip()
                if code_content:
                    markdown += '`' + code_content + '`'
            elif child.name == 'pre':
                # 处理代码块
                code_content = self._extract_code_from_pre(child)
                language = self._detect_code_language(child)
                if code_content:
                    if language:
                        markdown += f'\n```{language}\n{code_content}\n```\n'
                    else:
                        markdown += f'\n```\n{code_content}\n```\n'
            else:
                # 递归处理其他元素
                content = self._html_to_markdown_recursive(child)
                markdown += content
        
        return markdown

    def _render_image_markdown(self, image_element, src, alt):
        """渲染图片 Markdown，并按需附加 OCR 结果。"""
        proxy_src = self._get_proxy_image_url(src)
        markdown = f'\n![{alt}]({proxy_src})\n'
        ocr_markdown = self._extract_image_ocr_markdown(image_element, src)
        if ocr_markdown:
            markdown += f'\n**图片OCR**\n\n{self._wrap_ocr_block(ocr_markdown)}\n'
        return markdown

    def _wrap_ocr_block(self, ocr_markdown):
        """将 OCR 结果包进引用块，并转义结构标记，避免破坏正文层级。"""
        content = (ocr_markdown or "").strip()
        if not content:
            return ""

        quoted_lines = []
        for line in content.splitlines():
            escaped = re.sub(r'^([#>*`\-\+])', r'\\\1', line)
            escaped = re.sub(r'^(\d+\.)', r'\\\1', escaped)
            quoted_lines.append(f"> {escaped}" if escaped else ">")

        return "\n".join(quoted_lines)

    def _extract_image_ocr_markdown(self, image_element, src):
        """对符合条件的图片调用 MinerU OCR，并返回清洗后的 Markdown。"""
        if not self.enable_image_ocr or not self.image_ocr_client:
            return ""

        cache_key = src
        if cache_key in self._image_ocr_cache:
            return self._image_ocr_cache[cache_key]

        if not self._should_ocr_image(image_element, src):
            self._image_ocr_cache[cache_key] = ""
            return ""

        try:
            response = self.session.get(src, timeout=60)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', 'application/octet-stream')
            filename = self._guess_image_filename(src, content_type)
            ocr_markdown = self.image_ocr_client.extract_markdown(
                image_bytes=response.content,
                filename=filename,
                content_type=content_type,
            ).strip()
            self._image_ocr_cache[cache_key] = ocr_markdown
            if self.verbose and ocr_markdown:
                print(f"图片 OCR 成功: {src}")
            return ocr_markdown
        except Exception as e:
            if self.verbose:
                print(f"图片 OCR 失败: {src} ({e})")
            self._image_ocr_cache[cache_key] = ""
            return ""

    def _should_ocr_image(self, image_element, src):
        """只对可能包含正文信息的大图做 OCR。"""
        if not src or not src.startswith('http'):
            return False

        lower_src = src.lower()
        if 'gif' in lower_src or 'wx_fmt=gif' in lower_src:
            return False

        width_candidates = [
            image_element.get('data-w'),
            image_element.get('width'),
            image_element.get('data-backw'),
        ]
        for width in width_candidates:
            if not width:
                continue
            try:
                if int(float(width)) < self.MINERU_IMAGE_MIN_WIDTH:
                    return False
            except Exception:
                continue

        return True

    def _guess_image_filename(self, src, content_type):
        """推断上传给 MinerU 的图片文件名。"""
        parsed = urllib.parse.urlparse(src)
        filename = os.path.basename(parsed.path) or 'image'
        if '.' not in filename:
            if 'png' in content_type:
                filename += '.png'
            elif 'jpeg' in content_type or 'jpg' in content_type:
                filename += '.jpg'
            elif 'webp' in content_type:
                filename += '.webp'
            else:
                filename += '.bin'
        return filename
    
    def _convert_list_to_markdown(self, list_element):
        """转换列表为Markdown"""
        markdown = ""
        items = list_element.find_all('li', recursive=False)
        
        for i, item in enumerate(items):
            content = self._html_to_markdown_recursive(item).strip()
            if content:
                if list_element.name == 'ol':
                    markdown += f"{i+1}. {content}\n"
                else:
                    markdown += f"- {content}\n"
        
        return markdown
    
    def _extract_code_from_pre(self, pre_element):
        """从pre元素中提取代码内容"""
        # 查找内部的code元素
        code_elem = pre_element.find('code')
        if code_elem:
            # 如果有code元素，提取其内容
            code_content = code_elem.get_text()
        else:
            # 如果没有code元素，直接提取pre的内容
            code_content = pre_element.get_text()
        
        # 清理代码内容
        code_content = code_content.strip()
        
        # 移除多余的空行，保持代码格式
        lines = code_content.split('\n')
        cleaned_lines = []
        for line in lines:
            if line.strip() or cleaned_lines:  # 保留非空行或已有内容时的空行
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def _detect_code_language(self, pre_element):
        """检测代码语言"""
        # 检查pre元素的class
        pre_classes = pre_element.get('class', [])
        
        # 常见语言映射
        language_mapping = {
            'language-python': 'python',
            'language-javascript': 'javascript',
            'language-js': 'javascript',
            'language-typescript': 'typescript',
            'language-ts': 'typescript',
            'language-java': 'java',
            'language-cpp': 'cpp',
            'language-c++': 'cpp',
            'language-c': 'c',
            'language-csharp': 'csharp',
            'language-c#': 'csharp',
            'language-go': 'go',
            'language-rust': 'rust',
            'language-php': 'php',
            'language-ruby': 'ruby',
            'language-python3': 'python',
            'language-py': 'python',
            'language-html': 'html',
            'language-css': 'css',
            'language-scss': 'scss',
            'language-sass': 'sass',
            'language-json': 'json',
            'language-xml': 'xml',
            'language-yaml': 'yaml',
            'language-yml': 'yaml',
            'language-sql': 'sql',
            'language-bash': 'bash',
            'language-shell': 'bash',
            'language-sh': 'bash',
            'language-markdown': 'markdown',
            'language-md': 'markdown',
            'language-dockerfile': 'dockerfile',
            'language-docker': 'dockerfile',
            'language-git': 'git',
            'language-diff': 'diff',
            'language-text': 'text',
            'language-plain': 'text',
        }
        
        # 检查class中是否包含语言信息
        for class_name in pre_classes:
            if class_name in language_mapping:
                return language_mapping[class_name]
            # 也检查部分匹配
            for key, lang in language_mapping.items():
                if key in class_name:
                    return lang
        
        # 检查内部code元素的class
        code_elem = pre_element.find('code')
        if code_elem:
            code_classes = code_elem.get('class', [])
            for class_name in code_classes:
                if class_name in language_mapping:
                    return language_mapping[class_name]
                # 也检查部分匹配
                for key, lang in language_mapping.items():
                    if key in class_name:
                        return lang
        
        # 检查data-language属性
        data_lang = pre_element.get('data-language') or pre_element.get('lang')
        if data_lang:
            return data_lang.lower()
        
        # 检查内部code元素的data-language属性
        if code_elem:
            data_lang = code_elem.get('data-language') or code_elem.get('lang')
            if data_lang:
                return data_lang.lower()
        
        # 如果没有检测到语言，返回None
        return None
    
    def _get_proxy_image_url(self, original_url):
        """获取代理图片URL，解决防盗链问题"""
        if not original_url or not original_url.startswith('http'):
            return original_url
        
        encoded_url = urllib.parse.quote(original_url, safe='')
        base_url = f"https://images.weserv.nl/?url={encoded_url}"
        
        # GIF图片添加特殊参数
        if 'gif' in original_url.lower() or 'wx_fmt=gif' in original_url.lower():
            base_url += "&n=-1"
        
        return base_url

def _build_fetcher(enable_image_ocr=False, mineru_url=None, verbose=False):
    return ArticleFetcher(
        enable_image_ocr=enable_image_ocr,
        mineru_url=mineru_url,
        verbose=verbose,
    )


class HelpFormatter(argparse.RawTextHelpFormatter):
    pass


def _examples_text(examples):
    if not examples:
        return None
    return "Examples:\n" + "\n".join(f"  {example}" for example in examples)


def _create_parser(description, examples=None):
    return argparse.ArgumentParser(
        description=description,
        epilog=_examples_text(examples),
        formatter_class=HelpFormatter,
    )


def _create_subparser(subparsers, name, help_text, description=None, examples=None):
    return subparsers.add_parser(
        name,
        help=help_text,
        description=description or help_text,
        epilog=_examples_text(examples),
        formatter_class=HelpFormatter,
    )


def _maybe_run_quietly(output_json, verbose, func, *args, **kwargs):
    if output_json and not verbose:
        with redirect_stdout(io.StringIO()):
            return func(*args, **kwargs)
    return func(*args, **kwargs)


def _print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _wants_json_output(argv):
    return '--output-json' in (argv or [])


def fetcher_is_album_url(url):
    return 'mp.weixin.qq.com/mp/appmsgalbum' in (url or '')


def _count_candidate_articles(store, fakeid, only_undownloaded=True, limit=None):
    return len(store.list_articles(fakeid, only_undownloaded=only_undownloaded, limit=limit))


def _build_download_dry_run(service, args):
    targets = _resolve_account_targets(service, args)
    items = []
    for identifier in targets:
        account = service.store.get_account(identifier)
        candidate_count = _count_candidate_articles(
            service.store,
            account['fakeid'],
            only_undownloaded=not getattr(args, 'all_articles', False),
            limit=args.limit,
        )
        items.append(
            {
                'fakeid': account['fakeid'],
                'nickname': account['nickname'],
                'candidate_articles': candidate_count,
            }
        )
    return items


def _apply_output_flags(args):
    if getattr(args, 'all', False) or getattr(args, 'all_formats', False):
        return True, True, True, True
    return (
        getattr(args, 'html', False),
        getattr(args, 'json', False),
        getattr(args, 'pdf', False),
        True,
    )


def _run_fetch_cli(argv):
    parser = _create_parser(
        '获取文章内容并转换为Markdown',
        examples=[
            'wespy-plus "https://mp.weixin.qq.com/s/xxxxx"',
            'wespy-plus "https://mp.weixin.qq.com/s/xxxxx" --pdf',
            'wespy-plus "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=...&album_id=..." --album-only --max-articles 20',
            'wespy-plus "https://example.com/article" --output-json',
            'wespy-plus --interactive',
        ],
    )
    parser.add_argument('url', nargs='?', help='文章URL')
    parser.add_argument('-o', '--output', default='articles', help='输出目录 (默认: articles)')
    parser.add_argument('-v', '--verbose', action='store_true', help='显示详细信息')
    parser.add_argument('--interactive', action='store_true', help='显式进入交互模式')
    parser.add_argument('--dry-run', action='store_true', help='仅输出执行计划，不发起网络请求也不写入文件')
    parser.add_argument('--output-json', action='store_true', help='以 JSON 输出结果，便于 agent 或脚本消费')
    parser.add_argument('--html', action='store_true', help='同时保存HTML文件')
    parser.add_argument('--json', action='store_true', help='同时保存JSON信息文件')
    parser.add_argument('--pdf', action='store_true', help='同时保存PDF文件 (依赖 agent-browser)')
    parser.add_argument('--all', action='store_true', help='保存所有格式文件 (HTML, JSON, PDF, Markdown)')
    parser.add_argument('--max-articles', type=int, help='微信专辑最大下载文章数量 (默认: 10)')
    parser.add_argument('--album-only', action='store_true', help='仅获取专辑文章列表，不下载内容')
    parser.add_argument('--image-ocr', action='store_true', help='对正文中的大图调用 MinerU OCR，并把结果合并进 Markdown')
    parser.add_argument('--mineru-url', help='MinerU 服务地址 (默认读取 WESPY_MINERU_URL 或使用本地开发地址)')
    
    args = parser.parse_args(argv)
    
    # 只有显式指定时才进入交互模式，避免 agent 误入提示流程
    if args.interactive:
        print("文章获取工具")
        print("=" * 40)
        url = input("请输入文章URL: ").strip()
        if not url:
            print("URL不能为空!")
            sys.exit(1)
        output_dir = input("输出目录 (回车使用默认 'articles'): ").strip() or 'articles'
        
        # 交互模式询问输出格式
        print("\n输出格式选择:")
        print("1. 仅 Markdown (默认)")
        print("2. Markdown + HTML")
        print("3. Markdown + JSON")
        print("4. Markdown + PDF")
        print("5. 全部格式 (HTML + JSON + PDF + Markdown)")
        
        choice = input("请选择 (1-5, 回车使用默认1): ").strip() or '1'
        
        save_html = False
        save_json = False
        save_pdf = False
        save_markdown = True
        
        if choice == '2':
            save_html = True
        elif choice == '3':
            save_json = True
        elif choice == '4':
            save_pdf = True
        elif choice == '5':
            save_html = True
            save_json = True
            save_pdf = True

        # 交互模式默认值
        max_articles = 10
        album_only = False
        image_ocr = False
        mineru_url = None

    else:
        if not args.url:
            parser.error("缺少文章 URL。示例: wespy-plus \"https://mp.weixin.qq.com/s/xxxxx\"")
        url = args.url
        output_dir = args.output
        
        # 命令行模式处理输出格式
        if args.all:
            save_html = True
            save_json = True
            save_pdf = True
            save_markdown = True
        else:
            save_html = args.html
            save_json = args.json
            save_pdf = args.pdf
            save_markdown = True  # 默认总是保存Markdown

        max_articles = args.max_articles or 10
        album_only = args.album_only
        image_ocr = args.image_ocr
        mineru_url = args.mineru_url

    if args.dry_run:
        mode = 'album-list' if fetcher_is_album_url(url) and album_only else 'album-download' if fetcher_is_album_url(url) else 'article'
        payload = {
            'ok': True,
            'dry_run': True,
            'mode': mode,
            'url': url,
            'output_dir': output_dir,
            'options': {
                'save_html': save_html,
                'save_json': save_json,
                'save_pdf': save_pdf,
                'save_markdown': save_markdown,
                'max_articles': max_articles,
                'album_only': album_only,
                'image_ocr': image_ocr,
                'mineru_url': mineru_url or os.environ.get('WESPY_MINERU_URL'),
            },
        }
        if args.output_json:
            _print_json(payload)
        else:
            print("Dry run:")
            print(f"模式: {mode}")
            print(f"URL: {url}")
            print(f"输出目录: {output_dir}")
            print(
                f"输出格式: HTML={save_html}, JSON={save_json}, PDF={save_pdf}, Markdown={save_markdown}"
            )
        return

    if args.verbose:
        print(f"URL: {url}")
        print(f"输出目录: {output_dir}")
        print(f"输出格式: HTML={save_html}, JSON={save_json}, PDF={save_pdf}, Markdown={save_markdown}")
        if hasattr(args, 'max_articles'):
            print(f"最大文章数量: {max_articles}")
        if hasattr(args, 'album_only'):
            print(f"仅获取列表: {album_only}")
        print(f"图片 OCR: {image_ocr}")
        if mineru_url:
            print(f"MinerU URL: {mineru_url}")

    fetcher = _build_fetcher(enable_image_ocr=image_ocr, mineru_url=mineru_url, verbose=args.verbose)

    # 检查是否为专辑URL
    if fetcher.album_fetcher.is_album_url(url):
        if album_only:
            # 仅获取专辑文章列表
            if not args.output_json:
                print("仅获取专辑文章列表...")
            articles = _maybe_run_quietly(
                args.output_json,
                args.verbose,
                fetcher.album_fetcher.fetch_album_articles,
                url,
                max_articles,
            )
            if articles:
                # 保存文章列表到文件
                list_file = os.path.join(output_dir, f"album_articles_{int(time.time())}.json")
                os.makedirs(output_dir, exist_ok=True)
                with open(list_file, 'w', encoding='utf-8') as f:
                    json.dump(articles, f, ensure_ascii=False, indent=2)
                if args.output_json:
                    _print_json({
                        'ok': True,
                        'mode': 'album-list',
                        'count': len(articles),
                        'list_file': list_file,
                        'articles': articles,
                    })
                else:
                    print(f"\n获取到 {len(articles)} 篇文章:")
                    for i, article in enumerate(articles, 1):
                        print(f"{i:2d}. {article['title']}")
                        print(f"     URL: {article['url']}")
                        print(f"     时间: {article.get('create_time', 'N/A')}")
                        if i < len(articles):
                            print()
                    print(f"\n文章列表已保存到: {list_file}")
            else:
                if args.output_json:
                    _print_json({'ok': False, 'mode': 'album-list', 'error': '未获取到任何文章'})
                else:
                    print("未获取到任何文章")
                sys.exit(1)
        else:
            # 批量下载专辑文章
            result = _maybe_run_quietly(
                args.output_json,
                args.verbose,
                fetcher.fetch_album_articles,
                url,
                output_dir,
                max_articles,
                save_html,
                save_json,
                save_markdown,
                save_pdf,
            )
            if result:
                if args.output_json:
                    _print_json({
                        'ok': True,
                        'mode': 'album-download',
                        'downloaded_count': len(result),
                        'output_dir': output_dir,
                    })
                else:
                    print(f"\n批量下载完成!")
                    print(f"成功下载: {len(result)} 篇文章")
            else:
                if args.output_json:
                    _print_json({'ok': False, 'mode': 'album-download', 'error': '专辑文章下载失败'})
                else:
                    print("专辑文章下载失败!")
                sys.exit(1)
    else:
        # 单篇文章处理
        result = _maybe_run_quietly(
            args.output_json,
            args.verbose,
            fetcher.fetch_article,
            url,
            output_dir,
            save_html,
            save_json,
            save_markdown,
            save_pdf,
        )

        if result and result.get('fetch_status') == 'unavailable':
            if args.output_json:
                _print_json({
                    'ok': False,
                    'mode': 'article',
                    'status': 'unavailable',
                    'url': url,
                    'reason': result.get('unavailable_reason') or '页面不可访问',
                })
            else:
                print("\n文章不可用，已跳过保存。")
                print(f"原因: {result.get('unavailable_reason') or '页面不可访问'}")
            sys.exit(1)
        elif result:
            if args.output_json:
                _print_json({
                    'ok': True,
                    'mode': 'article',
                    'article': {
                        'title': result['title'],
                        'author': result['author'],
                        'publish_time': result['publish_time'],
                        'url': result['url'],
                    },
                    'output_dir': output_dir,
                    'formats': {
                        'markdown': save_markdown,
                        'html': save_html,
                        'json': save_json,
                        'pdf': save_pdf,
                    },
                })
            else:
                print(f"\n成功获取文章!")
                print(f"标题: {result['title']}")
                print(f"作者: {result['author']}")
                print(f"发布时间: {result['publish_time']}")
        else:
            if args.output_json:
                _print_json({'ok': False, 'mode': 'article', 'error': '文章获取失败'})
            else:
                print("文章获取失败!")
            sys.exit(1)


def _build_subscription_parser():
    parser = _create_parser(
        '微信公众号订阅与批量正文下载',
        examples=[
            'wespy-plus auth login',
            'wespy-plus subscribe "人民日报"',
            'wespy-plus sync "人民日报"',
            'wespy-plus download-account "人民日报" --limit 1 --pdf',
            'wespy-plus sync --all --output-json',
        ],
    )
    parser.add_argument('-v', '--verbose', action='store_true', help='显示详细信息')
    parser.add_argument('--db-path', help='SQLite 数据库路径 (默认: ~/.wespy/wespy.db)')

    subparsers = parser.add_subparsers(dest='command', required=True)

    auth_parser = _create_subparser(
        subparsers,
        'auth',
        '管理公众号后台认证信息',
        examples=[
            'wespy-plus auth login',
            'wespy-plus auth set --token 123456 --cookie "pass_ticket=...; wap_sid2=...; ..."',
            'wespy-plus auth show',
        ],
    )
    auth_subparsers = auth_parser.add_subparsers(dest='auth_command', required=True)

    auth_set = _create_subparser(
        auth_subparsers,
        'set',
        '设置 token 和 cookie',
        examples=[
            'wespy-plus auth set --token 123456 --cookie "pass_ticket=...; wap_sid2=...; ..."',
            'wespy-plus auth set --token 123456 --cookie-file /tmp/mp-cookie.txt',
        ],
    )
    auth_set.add_argument('--token', required=True, help='公众号后台 token')
    auth_set.add_argument('--cookie', help='完整 Cookie 字符串')
    auth_set.add_argument('--cookie-file', help='从文件读取 Cookie 字符串')
    auth_set.add_argument('--output-json', action='store_true', help='以 JSON 输出结果')

    auth_login = _create_subparser(
        auth_subparsers,
        'login',
        '扫码登录公众号后台并自动写入 SQLite',
        examples=[
            'wespy-plus auth login',
            'wespy-plus auth login --qr-output /tmp/wespy-login.png --timeout 180',
        ],
    )
    auth_login.add_argument('--qr-output', help='二维码图片保存路径 (默认: ~/.wespy/login-qrcode.png)')
    auth_login.add_argument('--timeout', type=int, default=180, help='扫码登录超时时间，单位秒 (默认: 180)')
    auth_login.add_argument('--poll-interval', type=int, default=2, help='轮询间隔，单位秒 (默认: 2)')
    auth_login.add_argument('--output-json', action='store_true', help='以 JSON 输出结果')

    auth_show = _create_subparser(
        auth_subparsers,
        'show',
        '查看当前认证信息状态',
        examples=['wespy-plus auth show', 'wespy-plus auth show --output-json'],
    )
    auth_show.add_argument('--output-json', action='store_true', help='以 JSON 输出结果')

    auth_clear = _create_subparser(
        auth_subparsers,
        'clear',
        '清除当前认证信息',
        examples=['wespy-plus auth clear', 'wespy-plus auth clear --output-json'],
    )
    auth_clear.add_argument('--output-json', action='store_true', help='以 JSON 输出结果')

    subscribe_parser = _create_subparser(
        subparsers,
        'subscribe',
        '订阅指定公众号',
        examples=[
            'wespy-plus subscribe "人民日报"',
            'wespy-plus subscribe "https://mp.weixin.qq.com/s/xxxxx"',
            'wespy-plus subscribe "人民日报" --output-json',
        ],
    )
    subscribe_parser.add_argument('target', help='公众号名称关键词或公众号文章链接')
    subscribe_parser.add_argument('--output-json', action='store_true', help='以 JSON 输出结果')

    subscriptions_parser = _create_subparser(
        subparsers,
        'subscriptions',
        '列出已订阅公众号',
        examples=['wespy-plus subscriptions', 'wespy-plus subscriptions --output-json'],
    )
    subscriptions_parser.add_argument('--output-json', action='store_true', help='以 JSON 输出结果')

    sync_parser = _create_subparser(
        subparsers,
        'sync',
        '同步订阅公众号的文章列表',
        examples=[
            'wespy-plus sync "人民日报"',
            'wespy-plus sync --all',
            'wespy-plus sync "人民日报" --dry-run --output-json',
        ],
    )
    sync_parser.add_argument('account', nargs='?', help='公众号名称、别名或 fakeid')
    sync_parser.add_argument('--all', action='store_true', help='同步全部已订阅公众号')
    sync_parser.add_argument('--max-pages', type=int, help='限制单个公众号最多同步页数')
    sync_parser.add_argument('--dry-run', action='store_true', help='仅输出同步计划，不发起实际同步')
    sync_parser.add_argument('--output-json', action='store_true', help='以 JSON 输出结果')

    download_parser = _create_subparser(
        subparsers,
        'download-account',
        '批量下载公众号文章',
        examples=[
            'wespy-plus download-account "人民日报"',
            'wespy-plus download-account "人民日报" --limit 1 --pdf',
            'wespy-plus download-account --all-accounts --dry-run --output-json',
        ],
    )
    download_parser.add_argument('account', nargs='?', help='公众号名称、别名或 fakeid')
    download_parser.add_argument('--all-accounts', action='store_true', help='下载全部已订阅公众号')
    download_parser.add_argument('--all-articles', action='store_true', help='包含已下载文章，默认仅下载未下载文章')
    download_parser.add_argument('--limit', type=int, help='限制下载文章数量')
    download_parser.add_argument('--dry-run', action='store_true', help='仅输出下载计划，不发起下载')
    download_parser.add_argument('--output-json', action='store_true', help='以 JSON 输出结果')
    download_parser.add_argument('-o', '--output', default='articles', help='输出目录 (默认: articles)')
    download_parser.add_argument('--html', action='store_true', help='同时保存HTML文件')
    download_parser.add_argument('--json', action='store_true', help='同时保存JSON信息文件')
    download_parser.add_argument('--pdf', action='store_true', help='同时保存PDF文件 (依赖 agent-browser)')
    download_parser.add_argument('--all-formats', action='store_true', help='保存所有格式文件 (HTML, JSON, PDF, Markdown)')
    download_parser.add_argument('--image-ocr', action='store_true', help='对正文中的大图调用 MinerU OCR，并把结果合并进 Markdown')
    download_parser.add_argument('--mineru-url', help='MinerU 服务地址')

    sync_download_parser = _create_subparser(
        subparsers,
        'sync-and-download',
        '同步后下载未下载文章',
        examples=[
            'wespy-plus sync-and-download "人民日报"',
            'wespy-plus sync-and-download --all-accounts --limit 5 --pdf',
            'wespy-plus sync-and-download "人民日报" --dry-run --output-json',
        ],
    )
    sync_download_parser.add_argument('account', nargs='?', help='公众号名称、别名或 fakeid')
    sync_download_parser.add_argument('--all-accounts', action='store_true', help='同步并下载全部已订阅公众号')
    sync_download_parser.add_argument('--max-pages', type=int, help='限制单个公众号最多同步页数')
    sync_download_parser.add_argument('--limit', type=int, help='限制下载文章数量')
    sync_download_parser.add_argument('--dry-run', action='store_true', help='仅输出执行计划，不发起同步或下载')
    sync_download_parser.add_argument('--output-json', action='store_true', help='以 JSON 输出结果')
    sync_download_parser.add_argument('-o', '--output', default='articles', help='输出目录 (默认: articles)')
    sync_download_parser.add_argument('--html', action='store_true', help='同时保存HTML文件')
    sync_download_parser.add_argument('--json', action='store_true', help='同时保存JSON信息文件')
    sync_download_parser.add_argument('--pdf', action='store_true', help='同时保存PDF文件 (依赖 agent-browser)')
    sync_download_parser.add_argument('--all-formats', action='store_true', help='保存所有格式文件 (HTML, JSON, PDF, Markdown)')
    sync_download_parser.add_argument('--image-ocr', action='store_true', help='对正文中的大图调用 MinerU OCR，并把结果合并进 Markdown')
    sync_download_parser.add_argument('--mineru-url', help='MinerU 服务地址')

    return parser


def _resolve_cookie_value(args):
    if getattr(args, 'cookie', None):
        return args.cookie
    if getattr(args, 'cookie_file', None):
        with open(args.cookie_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    raise RuntimeError("请通过 --cookie 或 --cookie-file 提供 Cookie")


def _resolve_account_targets(service, args):
    if getattr(args, 'all', False) or getattr(args, 'all_accounts', False):
        accounts = service.list_accounts()
        if not accounts:
            raise RuntimeError("当前没有已订阅公众号。示例: wespy-plus subscribe \"人民日报\"")
        return [account['fakeid'] for account in accounts]
    if getattr(args, 'account', None):
        return [args.account]
    raise RuntimeError("请提供公众号名称/fakeid，或使用 --all/--all-accounts。示例: wespy-plus download-account \"人民日报\"")


def _run_subscription_cli(argv):
    parser = _build_subscription_parser()
    args = parser.parse_args(argv)
    output_json = getattr(args, 'output_json', False)

    store = SubscriptionStore(db_path=args.db_path)
    service = SubscriptionService(store, verbose=args.verbose)

    if args.command == 'auth':
        if args.auth_command == 'set':
            cookie = _resolve_cookie_value(args)
            service.set_auth(args.token, cookie)
            if output_json:
                _print_json({'ok': True, 'command': 'auth.set', 'db_path': store.db_path})
            else:
                print(f"已保存公众号后台认证信息到: {store.db_path}")
            return
        if args.auth_command == 'login':
            result = service.login_via_qrcode(
                qr_output_path=args.qr_output,
                timeout=args.timeout,
                poll_interval=args.poll_interval,
            )
            if output_json:
                _print_json({
                    'ok': True,
                    'command': 'auth.login',
                    'db_path': store.db_path,
                    'token': result['token'],
                    'nickname': result.get('nickname'),
                    'qr_path': result['qr_path'],
                })
            else:
                print("扫码登录成功")
                if result.get('nickname'):
                    print(f"公众号: {result['nickname']}")
                print(f"token: {result['token']}")
                print(f"二维码文件: {result['qr_path']}")
                print(f"数据库: {store.db_path}")
            return
        if args.auth_command == 'show':
            auth = service.get_auth()
            if not auth:
                if output_json:
                    _print_json({'ok': True, 'command': 'auth.show', 'configured': False, 'db_path': store.db_path})
                else:
                    print(f"未配置认证信息: {store.db_path}")
                return
            payload = {
                'ok': True,
                'command': 'auth.show',
                'configured': True,
                'db_path': store.db_path,
                'token': auth['token'],
                'cookie_length': len(auth['cookie']),
                'updated_at': auth['updated_at'],
                'updated_at_text': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(auth['updated_at'])),
            }
            if output_json:
                _print_json(payload)
            else:
                print(f"数据库: {store.db_path}")
                print(f"token: {auth['token']}")
                print(f"cookie长度: {len(auth['cookie'])}")
                print(f"更新时间: {payload['updated_at_text']}")
            return
        if args.auth_command == 'clear':
            service.clear_auth()
            if output_json:
                _print_json({'ok': True, 'command': 'auth.clear', 'db_path': store.db_path})
            else:
                print("已清除公众号后台认证信息")
            return

    if args.command == 'subscribe':
        account, resolved_query = _maybe_run_quietly(
            output_json,
            args.verbose,
            service.subscribe,
            args.target,
        )
        payload = {
            'ok': True,
            'command': 'subscribe',
            'account': account,
            'resolved_query': resolved_query,
        }
        if output_json:
            _print_json(payload)
        else:
            print(f"已订阅公众号: {account['nickname']}")
            print(f"fakeid: {account['fakeid']}")
            if resolved_query != args.target:
                print(f"解析目标: {resolved_query}")
        return

    if args.command == 'subscriptions':
        accounts = service.list_accounts()
        if not accounts:
            if output_json:
                _print_json({'ok': True, 'command': 'subscriptions', 'accounts': []})
            else:
                print("当前没有已订阅公众号")
            return
        if output_json:
            _print_json({'ok': True, 'command': 'subscriptions', 'accounts': accounts})
        else:
            for account in accounts:
                print(f"- {account['nickname']} ({account['fakeid']})")
                print(f"  已同步文章: {account.get('article_count', 0)}")
                print(f"  待下载文章: {account.get('pending_count', 0) or 0}")
        return

    if args.command == 'sync':
        targets = _resolve_account_targets(service, args)
        if getattr(args, 'dry_run', False):
            payload = {
                'ok': True,
                'command': 'sync',
                'dry_run': True,
                'targets': [service.store.get_account(identifier) for identifier in targets],
                'max_pages': args.max_pages,
            }
            if output_json:
                _print_json(payload)
            else:
                print("Dry run:")
                print(f"待同步公众号数: {len(payload['targets'])}")
                print(f"max_pages: {args.max_pages or 'all'}")
                for account in payload['targets']:
                    print(f"- {account['nickname']} ({account['fakeid']})")
            return

        results = []
        for identifier in _resolve_account_targets(service, args):
            result = _maybe_run_quietly(
                output_json,
                args.verbose,
                service.sync_account,
                identifier,
                max_pages=args.max_pages,
            )
            results.append(result)
            account = result['account']
            if not output_json:
                print(f"已同步公众号: {account['nickname']} ({account['fakeid']})")
                print(
                    f"页数: {result['pages']}, 新增文章: {result['new_articles']}, "
                    f"更新文章: {result['updated_articles']}, 本次扫描: {result['synced_articles']}"
                )
        if output_json:
            _print_json({'ok': True, 'command': 'sync', 'results': results})
        return

    if args.command in ('download-account', 'sync-and-download'):
        save_html, save_json, save_pdf, save_markdown = _apply_output_flags(args)
        targets = _resolve_account_targets(service, args)
        if getattr(args, 'dry_run', False):
            payload = {
                'ok': True,
                'command': args.command,
                'dry_run': True,
                'sync_first': args.command == 'sync-and-download',
                'targets': _build_download_dry_run(service, args),
                'output_dir': args.output,
                'formats': {
                    'markdown': save_markdown,
                    'html': save_html,
                    'json': save_json,
                    'pdf': save_pdf,
                },
                'limit': args.limit,
                'max_pages': getattr(args, 'max_pages', None),
            }
            if output_json:
                _print_json(payload)
            else:
                print("Dry run:")
                print(f"命令: {args.command}")
                print(f"输出目录: {args.output}")
                print(
                    f"输出格式: HTML={save_html}, JSON={save_json}, PDF={save_pdf}, Markdown={save_markdown}"
                )
                for item in payload['targets']:
                    print(
                        f"- {item['nickname']} ({item['fakeid']}), 待处理文章: {item['candidate_articles']}"
                    )
            return

        fetcher = _build_fetcher(
            enable_image_ocr=getattr(args, 'image_ocr', False),
            mineru_url=getattr(args, 'mineru_url', None),
            verbose=args.verbose,
        )

        results = []
        for identifier in targets:
            if args.command == 'sync-and-download':
                sync_result = _maybe_run_quietly(
                    output_json,
                    args.verbose,
                    service.sync_account,
                    identifier,
                    max_pages=args.max_pages,
                )
                if not output_json:
                    print(
                        f"已同步公众号: {sync_result['account']['nickname']} ({sync_result['account']['fakeid']}), "
                        f"新增文章: {sync_result['new_articles']}"
                    )
            else:
                sync_result = None

            result = _maybe_run_quietly(
                output_json,
                args.verbose,
                service.download_account,
                identifier,
                fetcher,
                output_root=args.output,
                only_undownloaded=not getattr(args, 'all_articles', False),
                limit=args.limit,
                save_html=save_html,
                save_json=save_json,
                save_markdown=save_markdown,
                save_pdf=save_pdf,
            )
            results.append({
                'sync': sync_result,
                'download': result,
            })
            if not output_json:
                print(
                    f"下载完成: {result['account']['nickname']} "
                    f"成功 {result['success']} / 总计 {result['total']} / "
                    f"不可用 {result.get('unavailable', 0)} / 失败 {result['failed']}"
                )
                if result['output_dir']:
                    print(f"输出目录: {result['output_dir']}")
        if output_json:
            _print_json({'ok': True, 'command': args.command, 'results': results})
        return


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    subcommands = {'auth', 'subscribe', 'subscriptions', 'sync', 'download-account', 'sync-and-download'}
    try:
        if any(arg in subcommands for arg in argv):
            _run_subscription_cli(argv)
        else:
            _run_fetch_cli(argv)
    except RuntimeError as e:
        if _wants_json_output(argv):
            _print_json({'ok': False, 'error': str(e)})
        else:
            print(f"错误: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        if _wants_json_output(argv):
            _print_json({'ok': False, 'error': '已中断'})
        else:
            print("已中断")
        sys.exit(1)

if __name__ == "__main__":
    main()
