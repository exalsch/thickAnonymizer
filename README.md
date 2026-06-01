# thickAnonymizer

Mass-anonymize files into readable tokens (`[PERSON_1]`, `[IP_1]`, `[HOST_1]`)
before using them with AI tools, then de-anonymize the AI's output back.

## Install (dev)
    pip install -e ".[dev]"
    python -m spacy download en_core_web_lg

## CLI
    thickanon anonymize C:\data --root C:\data --mapping C:\data\map.json --mode quick_review
    thickanon deanonymize C:\data --mapping C:\data\map.json

## Desktop app
    python -m thickanon.ui.app

## Build a Windows .exe
    pyinstaller packaging/thickanon.spec
    # dist/thickAnonymizer.exe
