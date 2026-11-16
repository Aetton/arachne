"""Golden Image credential defaults for legacy provision artifacts."""

from typing import Any


def golden_credentials_ref(metadata: dict[str, Any]) -> str:
    """Resolve the default target credential from the Golden Image profile.

    Legacy Brood spiders only expose the selected image key in flat metadata.
    The application injects this lookup into the generic Brood normalizer.
    """
    image = str(metadata.get("image") or "").strip().lower()
    if not image:
        return ""
    try:
        from golden_images import get_profile

        profile = get_profile(image)
    except Exception:
        return ""
    if not profile:
        return ""
    return str(profile.get("credentials_ref") or "").strip().lower()
