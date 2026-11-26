"""Small supplier catalog; no business permissions, credentials or execution."""
from enterprise.providers import volcengine_images, zhenzhen

ADAPTERS = {"zhenzhen": zhenzhen, "volcengine": volcengine_images}


def supplier_id(provider):
    explicit = (provider or {}).get("supplier")
    if explicit in ADAPTERS:
        return explicit
    if zhenzhen.is_zhenzhen(provider):
        return "zhenzhen"
    return "volcengine" if volcengine_images.is_provider(provider) else ""


def configure_provider(provider):
    adapter = ADAPTERS.get(provider.get("supplier"))
    return adapter.configure_provider(provider) if adapter else provider


def provider_presets():
    return {key: adapter.provider_preset() for key, adapter in ADAPTERS.items()}


def image_profile(provider, model):
    adapter = ADAPTERS.get(supplier_id(provider))
    return adapter.image_profile(provider, model) if adapter else {}


def public_image_profiles(provider):
    return {model: profile for model in (provider or {}).get("image_models", [])
            if (profile := image_profile(provider, model))}


def supports_managed_source(provider):
    return bool(supplier_id(provider))


def image_task_query_supported(provider):
    return getattr(ADAPTERS.get(supplier_id(provider)), "IMAGE_TASK_QUERY_SUPPORTED", True)
