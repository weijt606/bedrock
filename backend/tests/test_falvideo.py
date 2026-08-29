"""The video brief must remain truthful and usable beyond Nutella."""
from app.clients.falvideo import build_prompt, filmable


def test_pepsi_uses_only_a_tangible_ingredient_as_a_motif():
    """Additives must not turn into made-up imagery in the generated loop."""
    ingredients = ["Carbonated Water", "High Fructose Corn Syrup", "Caramel Color",
                   "Sugar", "Phosphoric Acid", "Caffeine"]
    assert filmable(ingredients) == ["Sugar"]

    prompt = build_prompt(ingredients, "can", has_photo=True)
    assert "Raw Sugar drift slowly into frame" in prompt
    assert "cocoa" not in prompt.lower()
    assert "hazelnut" not in prompt.lower()
    assert "deep brown" not in prompt.lower()


def test_no_photo_and_no_visual_ingredients_does_not_invent_nutella():
    prompt = build_prompt(["Phosphoric Acid", "Caramel Color"], None, has_photo=False)
    assert "plain dark surface" in prompt
    assert "cocoa" not in prompt.lower()
    assert "hazelnut" not in prompt.lower()


def test_nutella_keeps_its_tangible_ingredients():
    assert filmable(["Hazelnuts", "Palm Oil", "Cocoa", "Skimmed Milk Powder"]) == [
        "Hazelnuts", "Cocoa", "Skimmed Milk Powder"]
