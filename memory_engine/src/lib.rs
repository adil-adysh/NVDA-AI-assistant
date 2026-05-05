use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use redb::{Database, ReadOnlyTable, ReadableTable, Table, TableDefinition, TableError, TableHandle};
use std::collections::HashSet;
use std::sync::RwLock;

const DEFAULT_TABLE_NAME: &str = "kv";
const TABLE_CACHE_SOFT_CAP: usize = 1024;

#[pyclass]
struct MemoryEngine {
    db: Database,
    table_cache: RwLock<HashSet<&'static str>>,
}

impl MemoryEngine {
    fn intern_table_name(&self, name: &str) -> &'static str {
        {
            let cache = self.table_cache.read().unwrap();
            if let Some(&static_name) = cache.get(name) {
                return static_name;
            }
        }

        let mut cache = self.table_cache.write().unwrap();
        if let Some(&static_name) = cache.get(name) {
            return static_name;
        }

        let leaked: &'static str = Box::leak(name.to_string().into_boxed_str());
        if cache.len() < TABLE_CACHE_SOFT_CAP {
            cache.insert(leaked);
        }
        leaked
    }

    fn table_def(&self, name: &str) -> TableDefinition<'static, &'static str, String> {
        if name == DEFAULT_TABLE_NAME {
            return TableDefinition::new(DEFAULT_TABLE_NAME);
        }
        TableDefinition::new(self.intern_table_name(name))
    }
}

fn to_py_err<E: std::fmt::Display>(error: E) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

#[pymethods]
impl MemoryEngine {
    #[new]
    #[pyo3(signature = (path = None))]
    fn new(path: Option<String>) -> PyResult<Self> {
        let path = path.unwrap_or_else(|| "memory_engine.db".to_string());
        let db = Database::create(path).map_err(to_py_err)?;
        Ok(Self {
            db,
            table_cache: RwLock::new(HashSet::new()),
        })
    }

    fn ping(&self) -> String {
        "memory_engine ready".to_string()
    }

    #[pyo3(signature = (key, value, table = "kv"))]
    fn set(&self, key: String, value: String, table: &str) -> PyResult<()> {
        let tx = self.db.begin_write().map_err(to_py_err)?;
        {
            let mut table: Table<&str, String> = tx.open_table(self.table_def(table)).map_err(to_py_err)?;
            table.insert(key.as_str(), value).map_err(to_py_err)?;
        }
        tx.commit().map_err(to_py_err)
    }

    #[pyo3(signature = (key, table = "kv"))]
    fn get(&self, key: String, table: &str) -> PyResult<Option<String>> {
        let tx = self.db.begin_read().map_err(to_py_err)?;
        let table: ReadOnlyTable<&str, String> = match tx.open_table(self.table_def(table)) {
            Ok(table) => table,
            Err(TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(err) => return Err(to_py_err(err)),
        };
        Ok(table
            .get(key.as_str())
            .map_err(to_py_err)?
            .map(|value| value.value().to_string()))
    }

    #[pyo3(signature = (key, table = "kv"))]
    fn contains(&self, key: String, table: &str) -> PyResult<bool> {
        let tx = self.db.begin_read().map_err(to_py_err)?;
        let table = match tx.open_table(self.table_def(table)) {
            Ok(table) => table,
            Err(TableError::TableDoesNotExist(_)) => return Ok(false),
            Err(err) => return Err(to_py_err(err)),
        };
        Ok(table.get(key.as_str()).map_err(to_py_err)?.is_some())
    }

    #[pyo3(signature = (key, table = "kv"))]
    fn delete(&self, key: String, table: &str) -> PyResult<bool> {
        let tx = self.db.begin_write().map_err(to_py_err)?;
        let table_def = self.table_def(table);

        let mut table = match tx.open_table(table_def) {
            Ok(table) => table,
            Err(TableError::TableDoesNotExist(_)) => return Ok(false),
            Err(err) => return Err(to_py_err(err)),
        };

        let deleted = table.remove(key.as_str()).map_err(to_py_err)?.is_some();
        drop(table);
        tx.commit().map_err(to_py_err)?;
        Ok(deleted)
    }

    #[pyo3(signature = (table = "kv"))]
    fn keys(&self, table: &str) -> PyResult<Vec<String>> {
        let tx = self.db.begin_read().map_err(to_py_err)?;
        let table_def = self.table_def(table);
        let table = match tx.open_table(table_def) {
            Ok(table) => table,
            Err(TableError::TableDoesNotExist(_)) => return Ok(Vec::new()),
            Err(err) => return Err(to_py_err(err)),
        };
        let mut keys = Vec::with_capacity(16);
        for item in table.iter().map_err(to_py_err)? {
            let (key, _) = item.map_err(to_py_err)?;
            keys.push(key.value().to_string());
        }
        Ok(keys)
    }

    fn table_names(&self) -> PyResult<Vec<String>> {
        let tx = self.db.begin_read().map_err(to_py_err)?;
        let mut tables = Vec::new();
        for table in tx.list_tables().map_err(to_py_err)? {
            tables.push(table.name().to_string());
        }
        tables.sort();
        Ok(tables)
    }

    fn table_exists(&self, table: &str) -> PyResult<bool> {
        let tx = self.db.begin_read().map_err(to_py_err)?;
        for table_handle in tx.list_tables().map_err(to_py_err)? {
            if table_handle.name() == table {
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn create_table(&self, table: &str) -> PyResult<bool> {
        let tx = self.db.begin_write().map_err(to_py_err)?;
        tx.open_table(self.table_def(table)).map_err(to_py_err)?;
        tx.commit().map_err(to_py_err)?;
        Ok(true)
    }

    fn delete_table(&self, table: &str) -> PyResult<bool> {
        let tx = self.db.begin_write().map_err(to_py_err)?;
        let deleted = tx
            .delete_table(self.table_def(table))
            .map_err(to_py_err)?;
        tx.commit().map_err(to_py_err)?;
        Ok(deleted)
    }

    fn rename_table(&self, table: &str, new_name: &str) -> PyResult<bool> {
        let tx = self.db.begin_write().map_err(to_py_err)?;
        let table_def = self.table_def(table);
        let new_table_def = self.table_def(new_name);
        tx.rename_table(table_def, new_table_def)
            .map_err(to_py_err)?;
        tx.commit().map_err(to_py_err)?;
        Ok(true)
    }

    fn compact(&mut self) -> PyResult<bool> {
        self.db.compact().map_err(to_py_err)
    }

    fn check_integrity(&mut self) -> PyResult<bool> {
        self.db.check_integrity().map_err(to_py_err)
    }

    fn cache_evictions(&self) -> PyResult<u64> {
        Ok(self.db.cache_stats().evictions())
    }
}

#[pymodule]
fn memory_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<MemoryEngine>()?;
    Ok(())
}
