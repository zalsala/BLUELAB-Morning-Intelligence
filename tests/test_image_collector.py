from pipeline.image_collector import extract_declared_image
from pipeline.image_provenance import audit_image_provenance


def test_extract_prefers_og_image_from_exact_article_html():
    html = '<html><head><meta property="og:image" content="/media/photo.jpg"></head><body></body></html>'
    url, method = extract_declared_image(html, 'https://example.com/news/123')
    assert url == 'https://example.com/media/photo.jpg'
    assert method == 'og:image'


def test_extract_rejects_logo_placeholder():
    html = '<html><head><meta property="og:image" content="https://cdn.example.com/assets/logo.png"></head></html>'
    url, method = extract_declared_image(html, 'https://example.com/news/123')
    assert url is None
    assert method is None


def test_provenance_requires_exact_page_chain_and_verified_raster():
    article = {
        'link': 'https://example.com/news/123',
        'image_candidate': {
            'status': 'VERIFIED',
            'url': 'https://cdn.example.net/photo.jpg',
            'method': 'og:image',
            'page_url': 'https://example.com/news/123',
            'content_type': 'image/jpeg',
            'content_hash': 'a' * 64,
        },
    }
    prov = audit_image_provenance(article)
    assert prov['status'] == 'VERIFIED_PROVENANCE'
    assert prov['url'] == 'https://cdn.example.net/photo.jpg'


def test_provenance_rejects_candidate_from_different_page():
    article = {
        'link': 'https://example.com/news/123',
        'image_candidate': {
            'status': 'VERIFIED',
            'url': 'https://cdn.example.net/photo.jpg',
            'method': 'og:image',
            'page_url': 'https://example.com/news/999',
            'content_type': 'image/jpeg',
            'content_hash': 'b' * 64,
        },
    }
    prov = audit_image_provenance(article)
    assert prov['status'] == 'EXPLICIT_NULL'
    assert prov['reason'] == 'PAGE_URL_MISMATCH'


def test_provenance_rejects_non_raster_content():
    article = {
        'link': 'https://example.com/news/123',
        'image_candidate': {
            'status': 'VERIFIED',
            'url': 'https://cdn.example.net/photo.svg',
            'method': 'og:image',
            'page_url': 'https://example.com/news/123',
            'content_type': 'image/svg+xml',
            'content_hash': 'c' * 64,
        },
    }
    prov = audit_image_provenance(article)
    assert prov['status'] == 'EXPLICIT_NULL'
    assert prov['reason'] == 'INVALID_IMAGE_CONTENT_TYPE'
