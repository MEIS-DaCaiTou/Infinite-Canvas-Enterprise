"""Video result URLs, excluding cover/last-frame images and reference metadata."""
from urllib.parse import urlsplit

CONTAINERS = ("videos", "outputs", "data", "result", "content")
VIDEO_URL_KEYS = (
    "url", "video_url", "videoUrl", "mp4_url", "mp4Url", "output", "output_url", "outputUrl",
    "download_url", "downloadUrl", "video", "src", "uri", "path",
)
NON_VIDEO_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp", ".svg", ".tif", ".tiff",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
}


def video_output_urls(raw):
    """Retain legacy nesting and extensionless signed downloads, in result order.

    Explicit last_frame/thumbnail and remixed-from fields are metadata, never
    extra completed videos. Media with an opaque URL is finally checked by the
    application's existing download step using its actual response type.
    """
    urls, previews = [], []
    def collect(value, destination):
        if isinstance(value, str):
            if not value.startswith(("http://", "https://", "/output/", "/assets/")):
                return
            path = urlsplit(value).path.lower()
            if any(path.endswith(suffix) for suffix in NON_VIDEO_SUFFIXES):
                return
            if value not in destination:
                destination.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item, destination)
        elif isinstance(value, dict):
            media_type = str(value.get("type") or value.get("mime_type") or "").lower()
            if media_type.startswith(("image", "audio")):
                return
            for key in CONTAINERS + VIDEO_URL_KEYS:
                if key in value:
                    collect(value[key], destination)
            for key in ("preview_url", "previewUrl"):
                if key in value:
                    collect(value[key], previews)
    if isinstance(raw, dict):
        collect(raw, urls)
    return urls or previews
