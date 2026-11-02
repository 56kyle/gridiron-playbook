use std::fmt::Display;
use std::io::Cursor;
use std::panic::{catch_unwind, UnwindSafe};

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use uesave::Save;

// uesave 0.7.1 can unwind on malformed data, including invalid UTF-16 strings.
fn convert<T, E: Display>(
    context: &str,
    operation: impl FnOnce() -> Result<T, E> + UnwindSafe,
) -> PyResult<T> {
    match catch_unwind(operation) {
        Ok(result) => result.map_err(|error| PyValueError::new_err(format!("{context}: {error}"))),
        Err(_) => Err(PyValueError::new_err(format!(
            "{context}: invalid save data"
        ))),
    }
}

/// Decode Unreal save bytes to a uesave JSON document. Raises ValueError on conversion failure.
#[pyfunction]
fn sav_to_json(save_bytes: &[u8]) -> PyResult<String> {
    let save = convert("Could not read Unreal save", || {
        Save::read(&mut Cursor::new(save_bytes))
    })?;
    convert("Could not serialize save to JSON", || {
        serde_json::to_string_pretty(&save)
    })
}

/// Encode uesave JSON to Unreal save bytes. The schemas field must precede root.
/// Raises ValueError on conversion failure.
#[pyfunction]
fn json_to_sav<'py>(py: Python<'py>, json_text: &str) -> PyResult<Bound<'py, PyBytes>> {
    let save: Save = convert("Invalid uesave JSON", || serde_json::from_str(json_text))?;
    let save_bytes = convert("Could not write Unreal save", || {
        let mut bytes = Vec::new();
        save.write(&mut bytes).map(|()| bytes)
    })?;
    Ok(PyBytes::new_bound(py, &save_bytes))
}

/// Formats the sum of two numbers as string.
#[pyfunction]
fn sum_as_string(a: usize, b: usize) -> PyResult<String> {
    Ok((a + b).to_string())
}

/// A Python module implemented in Rust.
#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sav_to_json, m)?)?;
    m.add_function(wrap_pyfunction!(json_to_sav, m)?)?;
    m.add_function(wrap_pyfunction!(sum_as_string, m)?)?;
    Ok(())
}
