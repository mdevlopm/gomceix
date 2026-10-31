"""`python3 -m gomceix` runs the launcher's shared entry point."""
import sys

from gomceix.core.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
