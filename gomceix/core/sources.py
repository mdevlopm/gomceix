"""Where the engine, Xodus and the other downloaded builds come from.

Gomceix does not build the Wine engine, Xodus or the WebKit runtime itself: it
downloads reviewed, SHA-256 pinned builds that the upstream project publishes.
This is the ONLY place that names that repository; everything else imports it.
If we ever host our own builds, change it here (and mind the source-offer duties
of the GPL/LGPL components).
"""

UPSTREAM_BUILDS_REPO = "Wyze3306/BedrockOnLinux"

# Names baked into those prebuilt, hash-pinned archives. Code that looks inside
# them has to use exactly these names; they are file names of someone else's
# build, not Gomceix's own naming (our own files use the "gomceix" name).
ARCHIVE_TAG = "bol"                          # suffix / version tag inside the engine archive
ARCHIVE_SHARE_DIR = "bedrock-on-linux"       # files/share/<this>/ inside the engine archive
WEBKIT_DIRNAME = "bol-webkit"                # directory name baked into the WebKit runtime's binaries
WEBVIEW_PLACEHOLDER = "@BOL_WEBVIEW@"        # path placeholder inside the WebKit runtime's loader cache
