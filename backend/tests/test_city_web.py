from datetime import datetime, timezone

from app.collectors.city_web import article_url, discover, parse_article


def test_city_article_preserves_date_and_excludes_sidebar():
    html = '''<div><h2 class="title_news">Реновация Затона <small>(29.10.2026, 14:46), просмотров: 4631</small></h2>
    <div style="display:none">СКРЫТАЯ РЕКЛАМА</div><div><p>В Павлодаре обсудили переселение жителей и строительство новых домов.</p></div></div>
    <aside>РЕКЛАМА</aside>'''
    item = parse_article(html, 'https://gorodpavlodar.kz/News_117838_2.html')
    assert item.kind == 'article' and item.author_id is None
    assert item.published_at == datetime(2026, 10, 29, 9, 46, tzinfo=timezone.utc)
    assert 'РЕКЛАМА' not in item.text and 'просмотров' not in item.text
    assert parse_article(html.replace('29.10.2026', 'неизвестно'), item.url) is None


def test_archive_date_is_not_replaced_with_collection_date():
    html = '''<div id="dle-content"><section class="entry-box standard-post">
    <div class="entry-thumb"><h2 class="entry-title">Отопление</h2>Автор, 7-10-2025, 15:52</div>
    <div class="entry-content"><p>В Павлодаре поступили сообщения о проблемах с началом отопительного сезона.</p></div>
    </section></div>'''
    item = parse_article(html, 'https://obozrenie.kz/17358-otoplenie.html')
    assert item.published_at == datetime(2025, 10, 7, 10, 52, tzinfo=timezone.utc)
    assert item.kind == 'article'


def test_discovery_is_bounded_to_public_article_paths_on_same_host():
    html = '<a href="/News_123_2.html">OK</a><a href="/News_123_2.html">duplicate</a><a href="https://obozrenie.kz/12-title.html">other</a><a href="/index.php">no</a>'
    assert discover(html, 'https://gorodpavlodar.kz') == ['https://gorodpavlodar.kz/News_123_2.html']
    for url in ('http://127.0.0.1/News_1_2.html', 'https://gorodpavlodar.kz/News_1_2.html?q=x',
                'https://gorodpavlodar.kz.evil/News_1_2.html', 'https://obozrenie.kz/user/a/'):
        assert not article_url(url)
