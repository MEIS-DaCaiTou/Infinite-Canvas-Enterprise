"""Seedream layer options shared by the existing image task and providers."""
from pydantic import BaseModel, Field


class LayerOptions(BaseModel):
    # Includes the base image. None keeps the channel's automatic limit.
    max_images: int | None = Field(default=None, ge=2, le=100)
    text_recognition: bool = False


def supports_layer_options(model):
    return model == "seedream-v5.5/layer-decomposition" or str(model).startswith("doubao-seedream-5-5-")


def layer_parameters(options):
    if options is None:
        return {}
    values = options.model_dump(exclude_none=True) if isinstance(options, LayerOptions) else options
    return {"layer_decomposition_options": values}
