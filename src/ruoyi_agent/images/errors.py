"""Errors shared by the image API, provider and durable worker."""


class ImageNotFound(Exception):
    """The image, task or owning conversation is unavailable."""


class ImageConflict(Exception):
    """The requested change conflicts with an active image task."""


class ImageInputError(ValueError):
    """An image request or uploaded image is invalid."""


class ImageProviderError(Exception):
    """The provider rejected a submission, or a provider request failed."""


class SubmissionUncertain(ImageProviderError):
    """A paid submission may have been accepted and must not be repeated."""
