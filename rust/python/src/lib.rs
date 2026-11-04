#![allow(
    clippy::useless_conversion,
    reason = "PyO3 0.22 generates PyErr-to-PyErr conversions inside its pyfunction wrappers."
)]
use gridiron_playbook_core as core;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

pyo3::create_exception!(gridiron_playbook, CoreError, PyValueError);

fn core_error(error: core::error::Error) -> PyErr {
    let exception = CoreError::new_err(error.message);
    Python::with_gil(|py| {
        let _ = exception.value_bound(py).setattr("code", error.code);
    });
    exception
}

fn indices(text: &str) -> PyResult<Vec<usize>> {
    serde_json::from_str(text).map_err(|error| core_error(error.into()))
}

#[pyfunction]
fn sav_to_json(save_bytes: &[u8]) -> PyResult<String> {
    core::sav_to_json(save_bytes).map_err(|error| {
        PyValueError::new_err(format!("Could not read Unreal save: {}", error.message))
    })
}

#[pyfunction]
fn json_to_sav<'py>(py: Python<'py>, json_text: &str) -> PyResult<Bound<'py, PyBytes>> {
    let bytes = core::json_to_sav(json_text).map_err(|error| {
        let prefix = if error.code == "write_save" {
            "Could not write Unreal save"
        } else {
            "Invalid uesave JSON"
        };
        PyValueError::new_err(format!("{prefix}: {}", error.message))
    })?;
    Ok(PyBytes::new_bound(py, &bytes))
}

#[pyfunction]
fn sum_as_string(a: usize, b: usize) -> PyResult<String> {
    a.checked_add(b)
        .map(|value| value.to_string())
        .ok_or_else(|| PyValueError::new_err("Integer sum overflow"))
}

#[pyfunction]
fn new_document() -> PyResult<String> {
    core::new_document().map_err(core_error)
}
#[pyfunction]
fn validate_document(document: &str) -> PyResult<()> {
    core::validate_document(document).map_err(core_error)
}
#[pyfunction]
fn inspect_document(document: &str) -> PyResult<String> {
    core::inspect_document(document).map_err(core_error)
}
#[pyfunction]
fn formation_data() -> PyResult<String> {
    core::formation_data().map_err(core_error)
}
#[pyfunction]
fn apply_edit(document: &str, command_json: &str) -> PyResult<String> {
    core::apply_edit(document, command_json).map_err(core_error)
}
#[pyfunction]
fn transfer_plays(
    source: &str,
    target: &str,
    indices_json: &str,
    insertion: usize,
    mode: &str,
) -> PyResult<String> {
    core::transfer_plays(source, target, indices_json, insertion, mode).map_err(core_error)
}
#[pyfunction]
fn decode_save(save_bytes: &[u8]) -> PyResult<String> {
    core::decode_save(save_bytes).map_err(core_error)
}
#[pyfunction]
fn encode_save<'py>(py: Python<'py>, document: &str) -> PyResult<Bound<'py, PyBytes>> {
    let bytes = core::encode_save(document).map_err(core_error)?;
    Ok(PyBytes::new_bound(py, &bytes))
}
#[pyfunction]
fn encode_share<'py>(
    py: Python<'py>,
    document: &str,
    indices_json: &str,
    kind: &str,
    precision: &str,
) -> PyResult<Bound<'py, PyBytes>> {
    let bytes = core::quickshare::encode_share(document, &indices(indices_json)?, kind, precision)
        .map_err(core_error)?;
    Ok(PyBytes::new_bound(py, &bytes))
}
#[pyfunction]
fn inspect_share(data: &[u8]) -> PyResult<String> {
    core::quickshare::inspect_share(data).map_err(core_error)
}
#[pyfunction]
fn import_share(template_doc: &str, data: &[u8]) -> PyResult<String> {
    core::quickshare::import_share(template_doc, data).map_err(core_error)
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("CoreError", m.py().get_type_bound::<CoreError>())?;
    m.add_function(wrap_pyfunction!(sav_to_json, m)?)?;
    m.add_function(wrap_pyfunction!(json_to_sav, m)?)?;
    m.add_function(wrap_pyfunction!(sum_as_string, m)?)?;
    m.add_function(wrap_pyfunction!(new_document, m)?)?;
    m.add_function(wrap_pyfunction!(validate_document, m)?)?;
    m.add_function(wrap_pyfunction!(inspect_document, m)?)?;
    m.add_function(wrap_pyfunction!(formation_data, m)?)?;
    m.add_function(wrap_pyfunction!(apply_edit, m)?)?;
    m.add_function(wrap_pyfunction!(transfer_plays, m)?)?;
    m.add_function(wrap_pyfunction!(decode_save, m)?)?;
    m.add_function(wrap_pyfunction!(encode_save, m)?)?;
    m.add_function(wrap_pyfunction!(encode_share, m)?)?;
    m.add_function(wrap_pyfunction!(inspect_share, m)?)?;
    m.add_function(wrap_pyfunction!(import_share, m)?)?;
    Ok(())
}
