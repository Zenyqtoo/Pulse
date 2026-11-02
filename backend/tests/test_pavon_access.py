import httpx
import pytest

from app.collectors import pavon
from app.collectors.base import CollectorError


def test_pavon_obeys_crawl_delay_and_prioritizes_requested_post(monkeypatch):
    calls, pauses = [], []
    def handler(request):
        calls.append(request.url.path)
        text = 'User-agent: *\nAllow: /\nCrawl-delay: 75' if request.url.path == '/robots.txt' else '<a href="/post/view/1">Other article</a>'
        return httpx.Response(200, text=text)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(pavon.httpx, 'Client', lambda **kwargs: client)
    monkeypatch.setattr(pavon.time, 'sleep', pauses.append)
    monkeypatch.setattr(pavon, 'parse_article', lambda html, url: ([], 1))
    pavon.PavonCommentsCollector({'posts': ['99'], 'max_articles': 1}).fetch(None)
    assert calls == ['/robots.txt', '/', '/post/view/99']
    assert pauses == [75, 75]


def test_pavon_does_not_fetch_disallowed_page(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, text='User-agent: *\nDisallow: /')
    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(pavon.httpx, 'Client', lambda **kwargs: client)
    with pytest.raises(CollectorError, match='robots.txt'):
        pavon.PavonCommentsCollector({}).fetch(None)
    assert calls == ['/robots.txt']
