"""Clipboard history, extended to images."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QGuiApplication, QImage

from wizard.config import ClipboardSettings
from wizard.features.clipboard import (
    MAX_STORED_EDGE,
    THUMBNAIL_EDGE,
    ClipboardWatcher,
    encode_image,
)
from wizard.storage import Storage


@pytest.fixture
def storage(tmp_path):
    with Storage(tmp_path / "db") as store:
        yield store


def image(width=300, height=200, colour="#3366AA") -> QImage:
    picture = QImage(width, height, QImage.Format.Format_RGB32)
    picture.fill(QColor(colour))
    return picture


def test_an_image_clip_is_listed_with_its_thumbnail(storage):
    png, thumb = encode_image(image())
    storage.add_image_clip(png, thumb, 300, 200)

    clip = storage.list_clips()[0]
    assert (clip.kind, clip.body) == ("image", "Image 300×200")
    assert clip.thumbnail == thumb
    assert storage.clip_image(clip.id) == png


def test_an_immediate_repeat_is_skipped(storage):
    png, thumb = encode_image(image())

    assert storage.add_image_clip(png, thumb, 300, 200) is not None
    assert storage.add_image_clip(png, thumb, 300, 200) is None


def test_images_are_pruned_on_their_own_tighter_limit(storage):
    storage.add_clip("un texte à garder")
    for index in range(6):
        png, thumb = encode_image(image(colour=f"#0000{index:02X}"))
        storage.add_image_clip(png, thumb, 300, 200, max_images=3)

    kinds = [clip.kind for clip in storage.list_clips(limit=50)]
    assert kinds.count("image") == 3
    # Text history is not collateral damage of image pruning.
    assert kinds.count("text") == 1


def test_text_equal_to_an_image_label_is_not_mistaken_for_a_repeat(storage):
    png, thumb = encode_image(image())
    storage.add_image_clip(png, thumb, 300, 200)

    assert storage.add_clip("Image 300×200") is not None


def test_a_text_clip_has_no_image(storage):
    clip_id = storage.add_clip("bonjour")

    assert storage.clip_image(clip_id) is None


def test_large_images_are_capped_and_thumbnails_are_small():
    png, thumb = encode_image(image(5000, 2500))

    stored, preview = QImage.fromData(png), QImage.fromData(thumb)
    assert max(stored.width(), stored.height()) == MAX_STORED_EDGE
    assert max(preview.width(), preview.height()) == THUMBNAIL_EDGE


# -- the watcher -------------------------------------------------------------


def test_a_copied_image_is_recorded(storage):
    watcher = ClipboardWatcher(storage, ClipboardSettings())
    QGuiApplication.clipboard().setImage(image(120, 80))
    QGuiApplication.processEvents()

    clip = storage.list_clips()[0]
    assert clip.kind == "image"
    assert clip.body == "Image 120×80"
    watcher.deleteLater()


def test_images_can_be_switched_off(storage):
    watcher = ClipboardWatcher(storage, ClipboardSettings(images=False))
    QGuiApplication.clipboard().setImage(image(120, 80))
    QGuiApplication.processEvents()

    assert storage.list_clips() == []
    watcher.deleteLater()


def test_restoring_an_image_does_not_record_it_again(storage):
    watcher = ClipboardWatcher(storage, ClipboardSettings())
    png, thumb = encode_image(image(50, 50))
    storage.add_image_clip(png, thumb, 50, 50)

    watcher.copy_image_to_clipboard(png)
    QGuiApplication.processEvents()

    assert len(storage.list_clips()) == 1
    assert not QGuiApplication.clipboard().image().isNull()
    watcher.deleteLater()
