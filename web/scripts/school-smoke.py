#!/usr/bin/env python3
"""Read-only release check for the public English school and existing app entry."""
import concurrent.futures
import io
import zipfile
from urllib.parse import urljoin, urlsplit
from html.parser import HTMLParser
import json
import re
import sys
import urllib.error
import urllib.request

base = sys.argv[1].rstrip('/')
pages = {
    '/': ['We teach children', '€2,000'],
    '/school/projects': ['Student projects', 'pcard'],
    '/mentors/dima': ['Dmitry Rubin'],
    '/mentors/darya': ['Darya Zhuykova'],
    '/school/contact': ['mailto:hi@wai.computer', '€2,000'],
    '/legal/offer': ['8 live online lessons', '1111B S Governors Ave'],
    '/legal/privacy': ['School website privacy'],
}
assets = set()
for path, markers in pages.items():
    with urllib.request.urlopen(base + path, timeout=20) as response:
        assert response.status == 200, path
        html = response.read().decode()
    for marker in markers + ['WaiWai, LLC', 'Delaware', '<html lang="en">']:
        assert marker in html, (path, marker)
    assert not re.search(r'[\u0400-\u04ff]|Russia|Moscow|RUB\b|₽|Severstal|Rosatom|IIDF|Netology', html, re.I), path
    assert not re.search(r'wai(?:[ .]|<span[^>]*>\.</span>)school|hello@mail\.waiwai\.is', html, re.I), path
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        json.loads(block)
    if path in ['/', '/school/contact', '/legal/offer']:
        assert '2 lessons per week' in html, path
        assert 'https://waiwai.is/pay/ce11c765-ecdd-4421-8996-09d0a3fe448f' in html, path
        assert not re.search(r'€700|€2,500|ten individual lessons|Introductory lesson|>free<', html), path
    assets.update(re.findall(r'/school-static/[a-zA-Z0-9_./-]+\.(?:webp|png|jpg|svg|woff2)', html))
    print('PASS', path)

projects = ['hallownest', 'block-modz', 'rifflegg', 'qfa-26', 'bouquet', 'mathai', 'escape-room', 'escape', 'bug-battle', 'bunker-zombie', 'striker', 'checkmedia']
project_pages = ['/school/projects/' + project for project in projects]
project_pages += ['/school/projects/' + project + '/app' for project in ['hallownest', 'rifflegg', 'mathai', 'bug-battle', 'striker']]
project_pages += ['/school/projects/checkmedia/variant-C-landing.html', '/school/projects/checkmedia/status.html']

class AssetParser(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.assets = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'base': self.page = urljoin(self.page, attrs.get('href', ''))
        value = attrs.get('src') if tag in ['img', 'script'] else attrs.get('href') if tag == 'link' or (tag == 'a' and attrs.get('href', '').endswith(('.mcaddon', '.mcpack', '.md'))) else None
        if value:
            url = urljoin(self.page, value)
            if urlsplit(url).netloc == urlsplit(base).netloc: self.assets.append(urlsplit(url).path)

for path in project_pages:
    with urllib.request.urlopen(base + path, timeout=20) as response:
        html = response.read().decode()
        assert response.status == 200 and re.search(r'<html[^>]* lang="en"', html), path
        assert html.startswith('<!DOCTYPE html>'), path
        if urlsplit(base).hostname == 'wai.computer':
            assert response.headers.get('X-Frame-Options', '').upper() == 'SAMEORIGIN', (path, 'project embedding blocked')
        assert not re.search(r'[\u0400-\u04ff]|Russia|Moscow|₽', html, re.I), path
    parser = AssetParser(base + path)
    parser.feed(html)
    assets.update(parser.assets)
print('PASS', len(project_pages), 'English project pages')

def check_asset(path):
    pack = path.endswith(('.mcaddon', '.mcpack'))
    with urllib.request.urlopen(urllib.request.Request(base + path, method='GET' if pack else 'HEAD'), timeout=20) as response:
        assert response.status == 200, path
        if pack:
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                assert archive.testzip() is None, path
                for name in archive.namelist():
                    if name.endswith(('.json', '.lang', '.js')):
                        source = archive.read(name).decode('utf-8-sig')
                        assert not re.search(r'[\u0400-\u04ff]', source), (path, name)
                        if name.endswith('.json'): json.loads(source)
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(check_asset, sorted(assets)))
print('PASS', len(assets), 'assets including translated Minecraft packs')

for project, collection in [('hallownest', 'waitlist'), ('block-modz', 'likes'), ('rifflegg', 'matches'), ('bouquet', 'saved'), ('escape', 'games')]:
    path = '/school-data/' + project + '/' + collection
    with urllib.request.urlopen(base + path, timeout=20) as response:
        data = json.load(response)
        assert data['ok'] and all(item.get('payload', {}).get('site') == 'wai.computer' for item in data['items']), path
print('PASS English-only project records')

for path, marker in [('/login', 'Sign in'), ('/terms', 'WaiWai, LLC'), ('/privacy', 'WaiWai, LLC')]:
    with urllib.request.urlopen(base + path, timeout=20) as response:
        assert response.status == 200 and marker.lower() in response.read().decode().lower(), path
    print('PASS', path)

with urllib.request.urlopen(base + '/ru', timeout=20) as response:
    assert response.geturl().rstrip('/') == base, 'legacy homepage must redirect'
print('PASS legacy homepage redirect')
