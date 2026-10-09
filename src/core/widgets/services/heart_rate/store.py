import json
import os
import tempfile
from pathlib import Path


class DeviceStore:
    """Atomic device JSON storage; never overwrite a file that failed validation.

    The caller serializes writes on the shared BLE loop. Runtime BLE objects are
    deliberately excluded. OSError/ValueError propagate for UI and log diagnostics.
    """

    def __init__(self, path: Path):
        self.path = path
        self._writable = True

    def load(self) -> dict[str, dict]:
        """Load address-keyed records; a missing file represents an empty store."""
        try:
            records = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(records, dict):
                raise ValueError("Device records must be an object")
            defaults = 0
            for address, record in records.items():
                if (
                    not isinstance(address, str)
                    or not address
                    or not isinstance(record, dict)
                    or record.get("address") != address
                    or not isinstance(record.get("name"), str)
                    or not isinstance(record.get("auto_connect"), bool)
                    or (
                        record.get("last_connected") is not None
                        and (type(record["last_connected"]) not in (int, float))
                    )
                ):
                    raise ValueError("Invalid saved device record")
                defaults += record["auto_connect"]
            if defaults > 1:
                raise ValueError("More than one default device")
            self._writable = True
            return records
        except FileNotFoundError:
            return {}
        except OSError, ValueError:
            self._writable = False
            raise

    def save(self, records: dict[str, dict]) -> None:
        """Flush a temporary file then replace the destination on the same volume.

        A failed replace leaves the old file intact. A corrupt/unreadable loaded
        store is read-only until repaired and successfully loaded again.
        """
        if not self._writable:
            raise ValueError("Saved device file requires repair before it can be overwritten")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, prefix=self.path.name, suffix=".tmp", delete=False
            ) as stream:
                temporary = stream.name
                json.dump(records, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
