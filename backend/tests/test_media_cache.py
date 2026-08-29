"""The loop has to survive a restart and never be paid for twice.

Videos were held in a module-level dict keyed by sample id, so restarting the
backend lost every file already generated, and searching the same product twice
generated it twice. These pin the disk cache that replaced it.
"""
import pytest

from app import media


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(media.cache, "_dir", tmp_path)
    yield


def test_the_same_product_resolves_to_the_same_key():
    assert media.key("Nutella") == media.key("  nutella  ")


def test_a_reference_photo_makes_a_different_loop():
    """Image-to-video and text-to-video are different briefs and different
    models, so they must not share a cached file."""
    assert media.key("Nutella") != media.key("Nutella", image_b64="aGk=")


def test_changing_the_style_invalidates_every_loop(monkeypatch):
    before = media.key("Nutella")
    monkeypatch.setattr(media, "STYLE_VERSION", "2")
    assert media.key("Nutella") != before


def test_a_job_in_flight_is_recalled_so_a_restart_resumes_polling():
    k = media.key("Nutella")
    media.remember_job(k, "minimax/h3-max/text-to-video", "req-1")
    assert media.recall(k) == {"model": "minimax/h3-max/text-to-video",
                               "request_id": "req-1"}


def test_a_finished_url_replaces_the_job_and_is_permanent():
    k = media.key("Nutella")
    media.remember_job(k, "m", "req-1")
    media.remember_url(k, "https://fal.media/x.mp4")
    assert media.recall(k) == {"url": "https://fal.media/x.mp4"}


def test_a_sample_still_finds_its_loop_after_the_process_is_gone():
    k = media.key("Nutella")
    media.bind("sample-abc", k)
    assert media.key_for("sample-abc") == k


def test_an_unknown_sample_recalls_nothing():
    assert media.key_for("never-seen") is None
    assert media.recall("never-seen") is None
