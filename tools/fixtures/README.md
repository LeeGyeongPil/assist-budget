# Regenerating the fixtures and golden files

The test fixtures are **not** written by hand. A real Home Assistant core writes
the `.storage` files, and the same core computes the golden answers the tests
compare against. Only developers who refresh the fixtures need this; the tests
and the tool itself never import Home Assistant.

Home Assistant 2026.11 needs Python 3.14 and pulls about 105 packages
(about 2.5 minutes). Use a separate virtual environment:

```bash
cd tools/fixtures
uv venv --python 3.14 /tmp/ha-venv
uv pip install --python /tmp/ha-venv/bin/python --index-url https://pypi.org/simple homeassistant==2026.11.3

# 1. the spec of the virtual house (synthetic, seeded, no real data)
python3 make_spec.py /tmp/ha-spec

# 2. let Home Assistant write the real .storage files
FIX=../../tests/fixtures/ha-2026.11.3
/tmp/ha-venv/bin/python ha_build_fixture.py /tmp/ha-spec $FIX/house house        # explicit exposure
/tmp/ha-venv/bin/python ha_build_fixture.py /tmp/ha-spec $FIX/defaults defaults  # default exposure rules

# 3. golden answers computed by Home Assistant itself
/tmp/ha-venv/bin/python ha_truth.py $FIX/house $FIX/house/golden
/tmp/ha-venv/bin/python ha_truth.py $FIX/defaults $FIX/defaults/golden

# 4. prompt texts for the profiles (reads Home Assistant sources, runs nothing)
#    the first file: https://raw.githubusercontent.com/home-assistant/core/2026.7.0/homeassistant/helpers/llm.py
python3 extract_prompts.py <2026.7 helpers/llm.py> <site-packages>/homeassistant/components/homeassistant/llm.py \
  <site-packages>/homeassistant/components/intent/llm.py <site-packages>/homeassistant/helpers/llm.py \
  ../../src/assist_budget/data/prompts.json

# keep the bundled sample house in sync with the `house` fixture
cp -R $FIX/house/.storage $FIX/house/.HA_VERSION ../../src/assist_budget/data/house/
```

If your pip is configured with a private index, keep `--index-url https://pypi.org/simple`.
Entity and device ids inside the files are random, so regenerated files differ byte for byte;
the numbers in the tests (`207` exposed, token counts) are re-measured and updated when you do.
`tests/test_demo.py::test_bundled_house_equals_the_test_fixture` fails if the bundled copy is stale.
