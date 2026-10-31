"""Archives zipfile cannot read end in the plain import error, not a raw exception."""
import zipfile
from unittest import mock

import pytest

from gomceix.core import content
from gomceix.core.log import BolError


@pytest.mark.parametrize("error", [RuntimeError("encrypted"), NotImplementedError("compression")])
def test_an_unreadable_archive_is_a_clean_error(tmp_path, error):
    archive = tmp_path / "pack.mcpack"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("manifest.json", "{}")
    with mock.patch.object(zipfile.ZipFile, "extractall", side_effect=error):
        with pytest.raises(BolError, match="was not imported"):
            content._extract_zip(archive, tmp_path / "out")
