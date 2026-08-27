"""Allow `python -m llama_console`"""
from .app import main

if __name__ == "__main__":
    import sys
    sys.exit(main())
