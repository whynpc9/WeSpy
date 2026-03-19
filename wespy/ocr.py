#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU OCR client utilities.
"""

import json
import re
import requests


class MinerUOCRClient:
    """调用 MinerU 服务，对图片做 OCR 并返回适合拼接进 Markdown 的文本。"""

    def __init__(self, server_url, backend="hybrid-auto-engine", lang_list=None, timeout=240):
        self.server_url = server_url.rstrip("/")
        self.backend = backend
        self.lang_list = lang_list or ["ch"]
        self.timeout = timeout
        self.session = requests.Session()

    def extract_markdown(self, image_bytes, filename, content_type="application/octet-stream"):
        """上传图片到 MinerU，并尽量提取出有价值的 Markdown。"""
        files = [('files', (filename, image_bytes, content_type))]
        data = {
            'backend': self.backend,
            'parse_method': 'ocr',
            'return_md': 'true',
            'return_middle_json': 'false',
            'return_model_output': 'false',
            'return_content_list': 'true',
            'return_images': 'false',
            'response_format_zip': 'false',
            'lang_list': self.lang_list,
        }

        response = self.session.post(
            f"{self.server_url}/file_parse",
            files=files,
            data=data,
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = response.json()
        results = payload.get('results') or {}
        if not results:
            return ""

        result = next(iter(results.values()))
        if not isinstance(result, dict):
            return ""

        markdown = self._build_markdown_from_content_list(result.get('content_list', ''))
        if markdown:
            return markdown

        return self._clean_md_content(result.get('md_content', ''))

    def _build_markdown_from_content_list(self, content_list_raw):
        """优先使用 content_list，自行裁掉 OCR 里的导航和页眉。"""
        if not content_list_raw:
            return ""

        try:
            items = json.loads(content_list_raw)
        except Exception:
            return ""

        text_items = []
        for item in items:
            if item.get('type') != 'text':
                continue
            text = self._normalize_text(item.get('text', ''))
            if not text:
                continue
            text_items.append({
                'text': text,
                'text_level': item.get('text_level'),
            })

        if not text_items:
            return ""

        anchor_index = self._find_anchor_index(text_items)
        rendered = []
        seen = set()

        for item in text_items[anchor_index:]:
            text = item['text']
            if self._should_skip_text_line(text):
                continue

            dedupe_key = re.sub(r'\s+', ' ', text)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            if item.get('text_level') and self._text_weight(text) >= 12:
                level = min(int(item['text_level']), 3)
                rendered.append(f"{'#' * level} {text}")
            else:
                rendered.append(text)

        markdown = "\n\n".join(rendered).strip()
        if self._markdown_weight(markdown) < 6:
            return ""

        return markdown

    def _clean_md_content(self, md_content):
        """回退到服务自带 md_content 时做轻量清洗。"""
        if not md_content:
            return ""

        lines = [self._normalize_text(line) for line in md_content.splitlines()]
        lines = [line for line in lines if line and not line.startswith('![](')]

        if not lines:
            return ""

        anchor_index = 0
        heading_candidates = [
            (idx, line.lstrip('# ').strip())
            for idx, line in enumerate(lines)
            if line.startswith('#') and self._text_weight(line.lstrip('# ').strip()) >= 12
        ]
        if heading_candidates:
            anchor_index = max(heading_candidates, key=lambda item: self._text_weight(item[1]))[0]
        else:
            for idx, line in enumerate(lines):
                plain = line.lstrip('# ').strip()
                if self._is_substantive_text(plain):
                    anchor_index = idx
                    break

        cleaned = []
        seen = set()
        for line in lines[anchor_index:]:
            plain = line.lstrip('# ').strip()
            if self._should_skip_text_line(plain):
                continue
            if plain in seen:
                continue
            seen.add(plain)
            cleaned.append(line)

        markdown = "\n\n".join(cleaned).strip()
        if self._markdown_weight(markdown) < 6:
            return ""
        return markdown

    def _find_anchor_index(self, text_items):
        heading_candidates = [
            (idx, item) for idx, item in enumerate(text_items)
            if item.get('text_level') and self._text_weight(item['text']) >= 12
        ]
        if heading_candidates:
            return max(heading_candidates, key=lambda pair: self._text_weight(pair[1]['text']))[0]

        for idx, item in enumerate(text_items):
            if self._is_substantive_text(item['text']):
                return idx

        return 0

    def _should_skip_text_line(self, text):
        if not text:
            return True
        if text.startswith('您现在所在的位置'):
            return True
        if re.search(r'\b首页\b', text) and '/' in text:
            return True
        if len(text) <= 8 and not self._contains_date(text) and not re.search(r'[。！？；：,.!?()]', text):
            return True
        return False

    def _is_substantive_text(self, text):
        return self._text_weight(text) >= 18 or (
            self._text_weight(text) >= 12 and bool(re.search(r'[。！？；：,.!?()]', text))
        )

    def _contains_date(self, text):
        return bool(re.search(r'\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2}', text))

    def _markdown_weight(self, markdown):
        plain = re.sub(r'[#>*`!\[\]\(\)-]', ' ', markdown)
        return self._text_weight(plain)

    def _text_weight(self, text):
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        latin_words = len(re.findall(r'\b[a-zA-Z0-9_]+\b', text))
        return latin_words + chinese_chars // 2

    def _normalize_text(self, text):
        return re.sub(r'\s+', ' ', text or '').strip()
