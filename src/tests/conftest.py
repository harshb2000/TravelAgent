import nltk


def pytest_configure(config):
    """Download required NLTK data packages before any test runs."""
    for pkg in ("punkt_tab", "stopwords", "wordnet"):
        nltk.download(pkg, quiet=True)
