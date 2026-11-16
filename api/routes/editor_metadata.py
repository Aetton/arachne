"""Admin-only endpoint for the shared scenario editor catalog."""

from fastapi import APIRouter, Depends

from auth.deps import require_role
from core.editor_metadata import scenario_dsl_metadata as build_metadata
from golden_images import list_profiles

router = APIRouter()


@router.get("/api/admin/scenario-dsl")
def scenario_dsl_metadata(user=Depends(require_role("admin"))):
    return build_metadata(list_profiles())
