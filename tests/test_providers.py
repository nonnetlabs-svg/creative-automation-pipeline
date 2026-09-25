from pipeline.providers import MockProvider

CORNER = (1023, 1023)  # far from the text, so it's pure background


def test_same_prompt_identical_pixels():
    a = MockProvider().generate("sparkling lime soda in a green aluminum can")
    b = MockProvider().generate("sparkling lime soda in a green aluminum can")
    assert a.tobytes() == b.tobytes()


def test_different_prompts_different_colors():
    a = MockProvider().generate("sparkling lime soda in a green aluminum can")
    b = MockProvider().generate("mixed berry soda in a purple aluminum can")
    assert a.getpixel(CORNER) != b.getpixel(CORNER)


def test_size_is_1024():
    assert MockProvider().generate("any prompt").size == (1024, 1024)


def test_name_is_mock():
    assert MockProvider().name == "mock"
