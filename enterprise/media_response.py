"""Response isolation for mutable/user-supplied media, never application HTML."""
from urllib.parse import quote


def media_response_headers(content_type, filename='download'):
    mime = str(content_type or '').split(';', 1)[0].strip().lower()
    headers = {'X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"}
    # SVG can execute script and embed active documents. Raster/audio/video keep
    # ordinary inline playback; other types remain downloadable as before.
    if mime in {'text/html','application/xhtml+xml','image/svg+xml','text/xml','application/xml'}:
        headers['Content-Disposition'] = "attachment; filename*=UTF-8''" + quote(filename)
    return headers
