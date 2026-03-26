#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF export helpers backed by agent-browser.
"""

import os
import shlex
import shutil
import subprocess
import time
import uuid


class AgentBrowserPDFExporter:
    """Use agent-browser to render a page URL as PDF."""

    def __init__(self, command=None, verbose=False):
        self.command = self._resolve_command(command or os.environ.get('WESPY_AGENT_BROWSER_CMD'))
        self.verbose = verbose

    def export_url(self, url, pdf_path):
        """Open a URL in agent-browser and save it as a PDF."""
        if not self.command:
            raise RuntimeError(
                "未找到 agent-browser 命令，请先安装 agent-browser，"
                "或通过 WESPY_AGENT_BROWSER_CMD 指定命令"
            )

        pdf_path = os.path.abspath(pdf_path)
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        session = f"wespy-{int(time.time())}-{uuid.uuid4().hex[:8]}"

        try:
            self._run(['--session', session, 'open', url])
            self._wait_for_page(session)
            self._run(['--session', session, 'pdf', pdf_path])
            return pdf_path
        finally:
            self._close_session(session)

    def _wait_for_page(self, session):
        """Wait until the page is reasonably stable before exporting."""
        try:
            self._run(['--session', session, 'wait', '--load', 'networkidle'])
        except RuntimeError:
            # Some pages keep background requests alive; a short fixed wait is a safe fallback.
            self._run(['--session', session, 'wait', '1500'])

    def _close_session(self, session):
        if not self.command:
            return
        try:
            subprocess.run(
                self.command + ['--session', session, 'close'],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass

    def _run(self, args):
        command = self.command + args
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )

        if self.verbose:
            if completed.stdout.strip():
                print(completed.stdout.strip())
            if completed.stderr.strip():
                print(completed.stderr.strip())

        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or '未知错误'
            raise RuntimeError(f"agent-browser 执行失败: {message}")

        return completed.stdout.strip()

    def _resolve_command(self, command):
        if command:
            return shlex.split(command)
        if shutil.which('agent-browser'):
            return ['agent-browser']
        if shutil.which('npx'):
            return ['npx', 'agent-browser']
        return None
