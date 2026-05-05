import importlib
import os
import tempfile
import unittest


class MemoryEngineTests(unittest.TestCase):
    def test_can_import_memory_engine(self):
        module = importlib.import_module("memory_engine")
        self.assertIsNotNone(module)
        self.assertTrue(hasattr(module, "MemoryEngine"))

    def test_memory_engine_ping_returns_expected_string(self):
        module = importlib.import_module("memory_engine")
        engine = module.MemoryEngine()
        self.assertEqual(engine.ping(), "memory_engine ready")

    def test_memory_engine_extension_module_file(self):
        module = importlib.import_module("memory_engine")
        self.assertTrue(hasattr(module, "__file__"), "memory_engine module should have a __file__ path")
        self.assertIsInstance(module.__file__, str)
        if os.name == "nt":
            self.assertTrue(
                module.__file__.lower().endswith((".pyd", "__init__.py")),
                module.__file__,
            )

    def test_memory_engine_crud_operations(self):
        module = importlib.import_module("memory_engine")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "memory_engine.db")
            engine = module.MemoryEngine(db_path)

            self.assertFalse(engine.contains("missing_key"))
            self.assertIsNone(engine.get("missing_key"))

            engine.set("user:1", "Alice")
            engine.set("user:2", "Bob")

            self.assertTrue(engine.contains("user:1"))
            self.assertEqual(engine.get("user:1"), "Alice")
            self.assertEqual(engine.get("user:2"), "Bob")

            engine.set("user:1", "Alice Updated")
            self.assertEqual(engine.get("user:1"), "Alice Updated")

            keys = sorted(engine.keys())
            self.assertEqual(keys, ["user:1", "user:2"])

            deleted = engine.delete("user:2")
            self.assertTrue(deleted)
            self.assertFalse(engine.contains("user:2"))
            self.assertIsNone(engine.get("user:2"))

            self.assertFalse(engine.delete("user:2"))
            self.assertEqual(sorted(engine.keys()), ["user:1"])

    def test_multiple_tables_and_db_operations(self):
        module = importlib.import_module("memory_engine")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "memory_engine.db")
            engine = module.MemoryEngine(db_path)

            self.assertFalse(engine.table_exists("users"))
            self.assertFalse(engine.table_exists("sessions"))
            self.assertFalse(engine.table_exists("missing"))
            self.assertEqual(engine.table_names(), [])

            engine.create_table("users")
            engine.create_table("sessions")
            engine.set("user:1", "Alice", "users")
            engine.set("user:2", "Bob", "users")
            engine.set("session:1", "active", "sessions")

            names = sorted(engine.table_names())
            self.assertEqual(names, ["sessions", "users"])
            self.assertTrue(engine.table_exists("users"))
            self.assertTrue(engine.table_exists("sessions"))
            self.assertFalse(engine.table_exists("missing"))

            self.assertIsNone(engine.get("missing_key", "users"))
            self.assertEqual(engine.get("user:1", "users"), "Alice")
            self.assertEqual(engine.get("session:1", "sessions"), "active")

            self.assertEqual(sorted(engine.keys("users")), ["user:1", "user:2"])
            self.assertEqual(engine.keys("sessions"), ["session:1"])

            self.assertTrue(engine.delete_table("sessions"))
            self.assertFalse(engine.table_exists("sessions"))
            self.assertNotIn("sessions", engine.table_names())
            self.assertFalse(engine.delete_table("sessions"))

            engine.rename_table("users", "people")
            self.assertFalse(engine.table_exists("users"))
            self.assertTrue(engine.table_exists("people"))
            self.assertEqual(engine.get("user:1", "people"), "Alice")
            self.assertEqual(sorted(engine.keys("people")), ["user:1", "user:2"])

            engine.set("user:3", "Charlie", "people")
            self.assertEqual(sorted(engine.keys("people")), ["user:1", "user:2", "user:3"])

            self.assertTrue(engine.compact())
            self.assertTrue(engine.check_integrity())
            self.assertIsInstance(engine.cache_evictions(), int)


if __name__ == "__main__":
    unittest.main()
